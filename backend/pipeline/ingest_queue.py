"""Durable ingest queue: item and job operations on the database (ADR-018).

Every state change goes through ``ingest_state``: updates only ever apply an
event to items in that event's legal source states. Worker-side writes run in
``BEGIN IMMEDIATE`` transactions (see ``write_session``) so a read-then-write
transaction can't fail on a stale WAL snapshot.

Callers:
- the ingest worker (claim, failures, recovery),
- the imports API (create, manifest, plan, user actions),
- tests.

See design/ingestion.md §3–§5.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import uuid
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.models import ImageGroup, ImportGroup, ImportItem, ImportJob, TagCategory
from backend.app.services import ImageParser
from backend.app.services import ingest_state as st
from backend.app.services.ingest_state import ItemEvent

from .error_classifier import KIND_FILE, KIND_SYSTEM, KIND_TRANSIENT

logger = logging.getLogger(__name__)

# Items whose bytes went missing are re-requested from the client.
KIND_BYTES_LOST = "bytes_lost"
# A local import's folder is missing (drive unplugged): the item goes back to ready and
# its job waits until the folder is back (design/local-ingest.md §4.4).
KIND_SOURCE_UNAVAILABLE = "source_unavailable"

ARCHIVE_EXTENSIONS = frozenset({".zip"})
_IN_CHUNK = 500  # Keep IN (...) lists far below SQLite's bound-variable limit


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


# Sessions


def _session() -> Session:
    from backend.app.models import get_engine, get_session_local

    return get_session_local(get_engine(settings.database_url))()


def begin_immediate(db: Session) -> None:
    """Take SQLite's write lock now rather than on the first write.

    Must be the first statement executed in the session. A deferred transaction
    that reads and then writes fails immediately with SQLITE_BUSY (busy_timeout
    doesn't apply) if another connection committed in between; IMMEDIATE waits
    for the lock up front instead.
    """
    db.execute(text("BEGIN IMMEDIATE"))


@contextmanager
def write_session() -> Iterator[Session]:
    """A session whose transaction holds the write lock from the start.

    Commits on clean exit, rolls back on exception.
    """
    db = _session()
    try:
        begin_immediate(db)
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# Paths


def staging_dir_for(job_id: str) -> Path:
    return settings.staging_dir / job_id


def staged_path(job_id: str, staging_key: str) -> Path:
    return staging_dir_for(job_id) / staging_key


def remove_staged(job_id: str, staging_key: str | None) -> None:
    if staging_key:
        staged_path(job_id, staging_key).unlink(missing_ok=True)


def kind_for_path(relative_path: str) -> str | None:
    """Item kind from the file extension, or None if unsupported."""
    ext = PurePosixPath(relative_path).suffix.lower()
    if ext in settings.supported_formats:
        return "image"
    if ext in settings.supported_video_formats:
        return "video"
    if ext in ARCHIVE_EXTENSIONS:
        return "archive"
    return None


_JUNK_NAMES = frozenset({".ds_store", "thumbs.db", "desktop.ini"})


def is_os_junk(relative_path: str) -> bool:
    """macOS/Windows metadata files that are never images (AppleDouble ``._*``, ``__MACOSX``).

    About 15% of image-extension files in a real library are AppleDouble junk.
    """
    parts = PurePosixPath(relative_path).parts
    name = parts[-1] if parts else ""
    return "__MACOSX" in parts or name.startswith("._") or name.lower() in _JUNK_NAMES


def normalise_relative_path(relative_path: str) -> str:
    """Canonical display path: forward slashes, no leading slash or ./ segments.

    Never used as a filesystem path; staging uses server-generated keys.
    """
    parts = [p for p in relative_path.replace("\\", "/").split("/") if p not in ("", ".")]
    return "/".join(parts)


# Jobs, manifest and planning


class ManifestSealedError(Exception):
    """Raised when adding to a job whose manifest has already been sealed."""


@dataclass(frozen=True)
class ManifestEntry:
    relative_path: str
    size: int | None = None
    last_modified: int | None = None
    image_type: str | None = None
    # Local imports: where the worker reads the file (design/local-ingest.md). The item
    # starts ready, since its bytes are already available.
    source_path: str | None = None


def create_job(
    db: Session, *, label: str | None = None, default_image_type: str = "battlemap"
) -> ImportJob:
    job = ImportJob(
        id=uuid.uuid4().hex,
        status=st.JOB_ACTIVE,
        source_label=label,
        default_image_type=default_image_type,
    )
    db.add(job)
    db.flush()
    return job


def add_manifest_items(
    db: Session,
    job: ImportJob,
    entries: Iterable[ManifestEntry],
    *,
    max_file_size: int | None = None,
) -> list[ImportItem]:
    """Create one item per manifest entry.

    - OS junk (``._*``, ``__MACOSX``, ``.DS_Store``...) is ignored entirely.
    - Other unsupported files become ``skipped`` items ("not an image"), visible
      in the report but not counted as errors.
    - Oversized files become ``failed`` items: the user expected them imported.

    Duplicate paths within the call are ignored; across calls the unique
    constraint rejects them.
    """
    if job.planned_at is not None:
        raise ManifestSealedError(job.id)

    items: list[ImportItem] = []
    seen: set[str] = set()
    for entry in entries:
        path = normalise_relative_path(entry.relative_path)
        if not path or path in seen or is_os_junk(path):
            continue
        seen.add(path)
        item = ImportItem(
            job_id=job.id,
            kind=kind_for_path(path) or "image",
            relative_path=path,
            filename=PurePosixPath(path).name,
            size=entry.size,
            last_modified=entry.last_modified,
            image_type=entry.image_type or job.default_image_type,
            state=st.AWAITING_BYTES,
        )
        _settle_new_item(item, entry, max_file_size)
        db.add(item)
        items.append(item)
    db.flush()
    return items


def _settle_new_item(item: ImportItem, entry: ManifestEntry, max_file_size: int | None) -> None:
    """Skip unsupported files, fail oversized ones; a local file's bytes are already here."""
    if kind_for_path(item.relative_path) is None:
        item.state = st.next_item_state(item.state, ItemEvent.SKIP)
        item.error_stage = "validate"
        item.error_reason = "Not a supported image, video or archive"
    elif max_file_size is not None and entry.size is not None and entry.size > max_file_size:
        _fail_validation(item, "File is larger than the import size limit")
    elif entry.source_path is not None:
        item.source_path = entry.source_path
        item.state = st.next_item_state(item.state, ItemEvent.BYTES_RECEIVED)


def _fail_validation(item: ImportItem, reason: str) -> None:
    item.state = st.next_item_state(item.state, ItemEvent.FILE_ERROR)
    item.error_kind = KIND_FILE
    item.error_stage = "validate"
    item.error_reason = reason


def _build_parser(db: Session) -> ImageParser:
    categories = db.query(TagCategory).all()
    return ImageParser(
        tag_categories=[{"name": c.name, "common_values": c.common_values} for c in categories]
    )


def _parsed_payload(parsed: dict, group_name: str) -> dict:
    return {
        "name": parsed.get("name") or group_name,
        "subgroup": parsed.get("subgroup"),
        "tags": parsed.get("tags") or [],
        "gridded": parsed.get("gridded"),
        "grid_width": parsed.get("grid_width"),
        "grid_height": parsed.get("grid_height"),
        "grid_type": parsed.get("grid_type"),
    }


def _existing_groups(db: Session, names: set[str]) -> dict[tuple[str, str | None], int]:
    """Map (base_name, author) → oldest matching ImageGroup id, querying in chunks."""
    found: dict[tuple[str, str | None], int] = {}
    ordered = sorted(names)
    for start in range(0, len(ordered), _IN_CHUNK):
        chunk = ordered[start : start + _IN_CHUNK]
        rows = (
            db.query(ImageGroup.id, ImageGroup.base_name, ImageGroup.author)
            .filter(ImageGroup.base_name.in_(chunk))
            .order_by(ImageGroup.id)
            .all()
        )
        for group_id, base_name, author in rows:
            found.setdefault((base_name, author), group_id)
    return found


def plan_job(db: Session, job_id: str) -> list[ImportGroup]:
    """Seal the manifest: parse paths, work out groups, resolve them against the gallery.

    Idempotent: a job that's already planned returns its existing groups. Groups
    whose (name, author) already exists in the gallery are marked
    ``merged_into_existing`` and will add to that gallery group.
    """
    job = db.get(ImportJob, job_id)
    if job is None:
        raise KeyError(job_id)
    if job.planned_at is not None:
        return db.query(ImportGroup).filter(ImportGroup.job_id == job_id).all()

    items = (
        db.query(ImportItem)
        .filter(
            ImportItem.job_id == job_id,
            ImportItem.kind != "archive",
            ImportItem.state != st.FAILED,
        )
        .all()
    )
    by_path = {item.relative_path: item for item in items}
    by_type: dict[str, list[str]] = {}
    for item in items:
        by_type.setdefault(item.image_type, []).append(item.relative_path)

    parser = _build_parser(db)
    planned: list[tuple[str | None, str, list[dict]]] = []
    for image_type, paths in sorted(by_type.items()):
        for group in parser.group_files(paths, image_type=image_type):
            author = group.get("author") or "Unknown"
            planned.append((author, group["group_name"], group["files"]))

    existing = _existing_groups(db, {name for _, name, _ in planned})
    groups: list[ImportGroup] = []
    for order, (author, group_name, _files) in enumerate(planned):
        existing_id = existing.get((group_name, author))
        groups.append(
            ImportGroup(
                job_id=job_id,
                author=author,
                group_name=group_name,
                image_group_id=existing_id,
                merged_into_existing=existing_id is not None,
                sort_order=order,
            )
        )
    db.add_all(groups)
    db.flush()  # one batched INSERT assigns every group id
    for import_group, (_author, group_name, files) in zip(groups, planned, strict=True):
        for file_entry in files:
            item = by_path[file_entry["relative_path"]]
            item.import_group_id = import_group.id
            item.parsed = json.dumps(_parsed_payload(file_entry["parsed"], group_name))

    job.planned_at = utcnow()
    db.flush()
    recompute_job_status(db, job_id)
    return groups


# Job status


def job_counts(db: Session, job_id: str) -> dict[str, int]:
    rows = (
        db.query(ImportItem.state, func.count(ImportItem.id))
        .filter(ImportItem.job_id == job_id)
        .group_by(ImportItem.state)
        .tuples()
        .all()
    )
    return dict(rows)


def recompute_job_status(db: Session, job_id: str) -> str:
    """The only writer of active ↔ completed. Call after any item change."""
    db.flush()  # sessions don't autoflush; the counts must see this transaction's changes
    job = db.get(ImportJob, job_id)
    if job is None:
        raise KeyError(job_id)
    new_status = st.compute_job_status(
        job.status, job.planned_at is not None, job_counts(db, job_id)
    )
    now = utcnow()
    if new_status != job.status:
        job.status = new_status
        job.completed_at = now if new_status == st.JOB_COMPLETED else None
    job.updated_at = now
    return new_status


# Byte receipt


def find_byte_duplicates(db: Session, hashes: Iterable[str]) -> dict[str, int]:
    """Map each hash that matches a library image (source or stored bytes) → oldest image id."""
    from backend.app.models import Image

    found: dict[str, int] = {}
    ordered = sorted(set(hashes))
    for start in range(0, len(ordered), _IN_CHUNK):
        chunk = ordered[start : start + _IN_CHUNK]
        rows = (
            db.query(Image.id, Image.content_hash, Image.stored_hash)
            .filter(Image.content_hash.in_(chunk) | Image.stored_hash.in_(chunk))
            .order_by(Image.id)
            .all()
        )
        wanted = set(chunk)
        for image_id, content_hash, stored_hash in rows:
            for h in (content_hash, stored_hash):
                if h in wanted:
                    found.setdefault(h, image_id)
    return found


def _mark_duplicate(item: ImportItem, image_id: int) -> None:
    item.state = st.next_item_state(item.state, ItemEvent.HASH_DUPLICATE)
    item.duplicate_of_image_id = image_id
    item.duplicate_tier = "bytes"


def mark_bytes_received(
    db: Session, item: ImportItem, *, staging_key: str, source_hash: str
) -> None:
    """Record staged bytes for an item awaiting them.

    If the bytes already exist in the library (and the user hasn't asked for a
    new copy) the item becomes a duplicate straight away; its staged bytes are
    kept so "Import as new copy" works without a re-upload.
    """
    item.staging_key = staging_key
    item.source_hash = source_hash
    item.error_kind = item.error_stage = item.error_reason = item.error_detail = None
    existing = None if item.allow_duplicate else find_byte_duplicates(db, [source_hash])
    if existing:
        _mark_duplicate(item, existing[source_hash])
    else:
        item.state = st.next_item_state(item.state, ItemEvent.BYTES_RECEIVED)
    job = db.get(ImportJob, item.job_id)
    if job is not None:
        job.last_upload_at = utcnow()
    # Every item transition must be followed by a status recompute; doing it here
    # means no caller can forget (an all-duplicates import must still complete).
    recompute_job_status(db, item.job_id)


def apply_client_hashes(db: Session, job_id: str, hashes: dict[int, str]) -> list[ImportItem]:
    """Record client-computed hashes for items awaiting bytes; skip uploads of known files.

    The client hash is only ever used to *skip* an upload. Bytes that are
    uploaded are always re-hashed server-side, and that hash is authoritative.
    """
    items = (
        db.query(ImportItem)
        .filter(ImportItem.job_id == job_id, ImportItem.id.in_(list(hashes)))
        .all()
    )
    awaiting = [i for i in items if i.state == st.AWAITING_BYTES and not i.allow_duplicate]
    existing = find_byte_duplicates(db, [hashes[i.id] for i in awaiting])
    for item in awaiting:
        image_id = existing.get(hashes[item.id])
        if image_id is not None:
            item.source_hash = hashes[item.id]
            _mark_duplicate(item, image_id)
    db.flush()
    recompute_job_status(db, job_id)
    return items


def dismiss_job(db: Session, job_id: str) -> None:
    """Hide a finished job from the activity dock. Never deletes anything."""
    job = db.get_one(ImportJob, job_id)
    job.dismissed_at = job.dismissed_at or utcnow()


class JobBusyError(Exception):
    """Raised when an operation must wait for the batch in progress to finish."""


def undo_job(db: Session, job_id: str):
    """Delete every image the job created, then the job itself (design §4.2).

    Cancels the job first. If a batch is mid-flight, raises JobBusyError so the
    caller can retry once it has committed. Gallery groups the job created (not
    ones it merged into) are deleted when they end up empty.

    Returns ``(deleted_count, pending)``: the caller commits, then calls
    ``pending.apply()`` to remove files and vectors.
    """
    from backend.app.services.deletion_service import delete_image_rows

    cancel_job(db, job_id)
    if job_counts(db, job_id).get(st.PROCESSING, 0):
        raise JobBusyError(job_id)

    from backend.app.models import Image

    images = db.query(Image).filter(Image.import_job_id == job_id).all()
    pending = delete_image_rows(db, images)

    created_group_ids = [
        group_id
        for (group_id,) in db.query(ImportGroup.image_group_id).filter(
            ImportGroup.job_id == job_id,
            ImportGroup.merged_into_existing.is_(False),
            ImportGroup.image_group_id.isnot(None),
        )
    ]
    if created_group_ids:
        still_used = select(Image.group_id).where(Image.group_id.in_(created_group_ids))
        db.query(ImageGroup).filter(
            ImageGroup.id.in_(created_group_ids), ImageGroup.id.not_in(still_used)
        ).delete(synchronize_session=False)

    db.query(ImportItem).filter(ImportItem.job_id == job_id).delete(synchronize_session=False)
    db.query(ImportGroup).filter(ImportGroup.job_id == job_id).delete(synchronize_session=False)
    db.query(ImportJob).filter(ImportJob.id == job_id).delete(synchronize_session=False)
    shutil.rmtree(staging_dir_for(job_id), ignore_errors=True)
    return len(images), pending


# Claiming (worker)


@dataclass(frozen=True)
class ClaimedItem:
    """Plain snapshot of a claimed item, safe to pass to worker threads."""

    id: int
    job_id: str
    import_group_id: int | None
    kind: str
    relative_path: str
    filename: str
    image_type: str
    parsed: dict
    staging_key: str | None
    source_hash: str | None
    attempts: int
    allow_duplicate: bool
    # Local imports: the file to read, and the job's folders (to tell a missing file
    # from a missing drive).
    source_path: str | None = None
    source_roots: tuple[str, ...] = ()
    # Grid sizes (NxM) named by other files in the same import group, both orientations.
    # Candidates for size-only grid detection, never truth (design/grid-detection-v3.md).
    sibling_grid_counts: tuple[tuple[int, int], ...] = ()


# Enough candidates for any real pack; bounds the per-image scoring work.
_MAX_SIBLING_GRID_COUNTS = 24


def _sibling_grid_counts(
    db: Session, group_ids: set[int]
) -> dict[int, tuple[tuple[int, int], ...]]:
    """Distinct NxM grid sizes parsed from file names, per import group."""
    found: dict[int, dict[tuple[int, int], None]] = {gid: {} for gid in group_ids}
    if not group_ids:
        return {}
    rows = db.query(ImportItem.import_group_id, ImportItem.parsed).filter(
        ImportItem.import_group_id.in_(group_ids), ImportItem.parsed.isnot(None)
    )
    for group_id, parsed_json in rows:
        parsed = json.loads(parsed_json)
        w, h = parsed.get("grid_width"), parsed.get("grid_height")
        counts = found[group_id]
        if w and h and len(counts) < _MAX_SIBLING_GRID_COUNTS:
            counts[(int(w), int(h))] = None
            counts[(int(h), int(w))] = None
    return {gid: tuple(counts) for gid, counts in found.items()}


def _snapshot(
    item: ImportItem,
    sibling_grid_counts: tuple[tuple[int, int], ...] = (),
    source_roots: tuple[str, ...] = (),
) -> ClaimedItem:
    return ClaimedItem(
        id=item.id,
        job_id=item.job_id,
        import_group_id=item.import_group_id,
        kind=item.kind,
        relative_path=item.relative_path,
        filename=item.filename,
        image_type=item.image_type,
        parsed=json.loads(item.parsed) if item.parsed else {},
        staging_key=item.staging_key,
        source_hash=item.source_hash,
        attempts=item.attempts,
        allow_duplicate=bool(item.allow_duplicate),
        sibling_grid_counts=sibling_grid_counts,
        source_path=item.source_path,
        source_roots=source_roots if item.source_path else (),
    )


def _claimable_filter(now: datetime):
    return (
        (ImportItem.state == st.READY)
        & (ImportItem.kind != "archive")
        & ((ImportItem.retry_after.is_(None)) | (ImportItem.retry_after <= now))
    )


def _pick_job(job_ids: list[str], after_job_id: str | None) -> str:
    """Round-robin: the job after the one served last, wrapping around."""
    if after_job_id in job_ids:
        return job_ids[(job_ids.index(after_job_id) + 1) % len(job_ids)]
    return job_ids[0]


def claim_next_batch(
    after_job_id: str | None, limit: int, now: datetime | None = None
) -> tuple[str | None, list[ClaimedItem]]:
    """Claim up to ``limit`` ready items from the next job in round-robin order.

    Within a job, items are claimed in group order so groups complete together.
    """
    now = now or utcnow()
    with write_session() as db:
        available = _claimable_jobs(db, now)
        if not available:
            return None, []
        job_id = _pick_job(list(available), after_job_id)
        items = (
            db.query(ImportItem)
            .outerjoin(ImportGroup, ImportGroup.id == ImportItem.import_group_id)
            .filter(ImportItem.job_id == job_id, _claimable_filter(now))
            .order_by(func.coalesce(ImportGroup.sort_order, 0), ImportItem.id)
            .limit(limit)
            .all()
        )
        for item in items:
            item.state = st.next_item_state(item.state, ItemEvent.CLAIM)
            item.attempts += 1
            item.retry_after = None
        db.flush()
        siblings = _sibling_grid_counts(
            db, {item.import_group_id for item in items if item.import_group_id is not None}
        )
        roots = tuple(available[job_id])
        return job_id, [
            _snapshot(
                item,
                siblings.get(item.import_group_id, ()) if item.import_group_id else (),
                roots,
            )
            for item in items
        ]


def _claimable_jobs(db: Session, now: datetime) -> dict[str, list[str]]:
    """Active, planned jobs with claimable items, oldest first, each with its folders.

    A local import whose folder is missing is left out: it waits, others carry on.
    """
    rows = (
        db.query(ImportJob.id, ImportJob.source_roots)
        .filter(
            ImportJob.status == st.JOB_ACTIVE,
            ImportJob.planned_at.isnot(None),
            db.query(ImportItem.id)
            .filter(ImportItem.job_id == ImportJob.id, _claimable_filter(now))
            .exists(),
        )
        .order_by(ImportJob.created_at, ImportJob.id)
    )
    jobs = {job_id: _roots(source_roots) for job_id, source_roots in rows}
    return {job_id: roots for job_id, roots in jobs.items() if not missing_roots(roots)}


def _roots(source_roots: str | None) -> list[str]:
    return json.loads(source_roots) if source_roots else []


def missing_roots(roots: Iterable[str]) -> list[str]:
    """A local import's folders that aren't there right now (drive unplugged, renamed)."""
    return [root for root in roots if not os.path.isdir(root)]


def job_missing_roots(job: ImportJob) -> list[str]:
    return missing_roots(_roots(job.source_roots))


# Failures (worker)


@dataclass(frozen=True)
class ItemFailure:
    item_id: int
    kind: str  # file | transient | system | bytes_lost
    stage: str
    reason: str
    detail: str = ""


# Failures that aren't the file's fault: the item goes back to ready, attempt refunded.
_REFUNDED = {
    KIND_SYSTEM: ItemEvent.SYSTEM_ERROR,
    KIND_SOURCE_UNAVAILABLE: ItemEvent.SOURCE_UNAVAILABLE,
}


def record_failures(failures: list[ItemFailure], now: datetime | None = None) -> set[str]:
    """Apply processing failures to their items. Returns the affected job ids.

    - file:       → failed
    - transient:  → ready with backoff, or failed once attempts are exhausted
    - system:     → ready with the attempt refunded (the queue pauses instead)
    - bytes_lost: → awaiting_bytes (the client is asked to upload again)
    """
    if not failures:
        return set()
    now = now or utcnow()
    job_ids: set[str] = set()
    with write_session() as db:
        items = {
            item.id: item
            for item in db.query(ImportItem).filter(
                ImportItem.id.in_([f.item_id for f in failures])
            )
        }
        for failure in failures:
            item = items.get(failure.item_id)
            if item is None or item.state != st.PROCESSING:
                continue
            job_ids.add(item.job_id)
            refund = _REFUNDED.get(failure.kind)
            if refund is not None:
                item.state = st.next_item_state(item.state, refund)
                item.attempts = max(0, item.attempts - 1)
                continue
            if failure.kind == KIND_BYTES_LOST:
                item.state = st.next_item_state(item.state, ItemEvent.BYTES_LOST)
                item.staging_key = None
            elif failure.kind == KIND_TRANSIENT and item.attempts < st.MAX_ATTEMPTS:
                item.state = st.next_item_state(item.state, ItemEvent.TRANSIENT_RETRY)
                item.retry_after = now + st.retry_delay(item.attempts)
            elif failure.kind == KIND_TRANSIENT:
                item.state = st.next_item_state(item.state, ItemEvent.GIVE_UP)
            else:
                item.state = st.next_item_state(item.state, ItemEvent.FILE_ERROR)
            item.error_kind = failure.kind
            item.error_stage = failure.stage
            item.error_reason = failure.reason
            item.error_detail = failure.detail[:4000] if failure.detail else None
        for job_id in job_ids:
            recompute_job_status(db, job_id)
    return job_ids


@dataclass(frozen=True)
class EarlyDuplicate:
    """A local item whose bytes are already in the library, found before decoding."""

    item_id: int
    image_id: int
    source_hash: str


def library_byte_duplicate(source_hash: str) -> int | None:
    """The library image with these exact bytes, if any (read-only; commit re-checks)."""
    with _session() as db:
        return find_byte_duplicates(db, [source_hash]).get(source_hash)


def record_early_duplicates(duplicates: list[EarlyDuplicate]) -> set[str]:
    """Mark processing items as byte duplicates. Returns the affected job ids."""
    if not duplicates:
        return set()
    job_ids: set[str] = set()
    with write_session() as db:
        items = {
            item.id: item
            for item in db.query(ImportItem).filter(
                ImportItem.id.in_([d.item_id for d in duplicates])
            )
        }
        for duplicate in duplicates:
            item = items.get(duplicate.item_id)
            if item is None or item.state != st.PROCESSING:
                continue
            item.state = st.next_item_state(item.state, ItemEvent.DUPLICATE_AT_COMMIT)
            item.duplicate_of_image_id = duplicate.image_id
            item.duplicate_tier = "bytes"
            item.source_hash = duplicate.source_hash
            job_ids.add(item.job_id)
        for job_id in job_ids:
            recompute_job_status(db, job_id)
    return job_ids


# Recovery (startup)


def recover_interrupted() -> dict[str, int]:
    """Return items left ``processing`` by a dead process to the queue.

    Items already claimed ``MAX_ATTEMPTS`` times are failed: a file that keeps
    crashing the process must not crash-loop the app. Nothing is deleted.
    """
    with write_session() as db:
        stranded = db.query(ImportItem).filter(ImportItem.state == st.PROCESSING).all()
        recovered = crashed = 0
        job_ids: set[str] = set()
        for item in stranded:
            job_ids.add(item.job_id)
            if item.attempts >= st.MAX_ATTEMPTS:
                item.state = st.next_item_state(item.state, ItemEvent.CRASH_LIMIT)
                item.error_kind = KIND_FILE
                item.error_stage = "processing"
                item.error_reason = "Repeatedly crashed during processing"
                crashed += 1
            else:
                item.state = st.next_item_state(item.state, ItemEvent.RECOVERED)
                recovered += 1
        for job_id in job_ids:
            recompute_job_status(db, job_id)
    if recovered or crashed:
        logger.warning(
            "Ingest recovery: %d item(s) re-queued, %d failed after repeated crashes",
            recovered,
            crashed,
        )
    return {"recovered": recovered, "crashed": crashed}


# User actions (imports API)


def _items_in(db: Session, job_id: str, states: Iterable[str], item_ids: list[int] | None):
    query = db.query(ImportItem).filter(
        ImportItem.job_id == job_id, ImportItem.state.in_(list(states))
    )
    if item_ids is not None:
        query = query.filter(ImportItem.id.in_(item_ids))
    return query


def _has_bytes(item: ImportItem) -> bool:
    """A local item's bytes are its source (a missing one fails again when it's read)."""
    if item.source_path:
        return True
    return bool(item.staging_key) and staged_path(item.job_id, item.staging_key).exists()


def _reopen(item: ImportItem, with_bytes: ItemEvent, without_bytes: ItemEvent) -> None:
    has_bytes = _has_bytes(item)
    item.state = st.next_item_state(item.state, with_bytes if has_bytes else without_bytes)
    if not has_bytes:
        item.staging_key = None
    item.attempts = 0
    item.retry_after = None
    item.error_kind = item.error_stage = item.error_reason = item.error_detail = None


def retry_items(db: Session, job_id: str, item_ids: list[int] | None = None) -> int:
    """Failed → ready (staged bytes present) or awaiting_bytes (they're gone)."""
    items = _items_in(db, job_id, st.sources_for(ItemEvent.RETRY), item_ids).all()
    for item in items:
        _reopen(item, ItemEvent.RETRY, ItemEvent.RETRY_NEEDS_BYTES)
    db.flush()
    recompute_job_status(db, job_id)
    return len(items)


def import_as_copy(db: Session, job_id: str, item_ids: list[int] | None = None) -> int:
    """Duplicate → processed as a fully independent new image (design §6)."""
    items = _items_in(db, job_id, st.sources_for(ItemEvent.IMPORT_AS_COPY), item_ids).all()
    for item in items:
        _reopen(item, ItemEvent.IMPORT_AS_COPY, ItemEvent.IMPORT_AS_COPY_NEEDS_BYTES)
        item.allow_duplicate = True
        item.duplicate_of_image_id = None
        item.duplicate_tier = None
    db.flush()
    recompute_job_status(db, job_id)
    return len(items)


def skip_items(
    db: Session,
    job_id: str,
    reason: str,
    *,
    states: Iterable[str] | None = None,
    import_group_id: int | None = None,
) -> int:
    """Mark open items skipped (cancel, finish-without, skip group, abandonment)."""
    allowed = st.sources_for(ItemEvent.SKIP)
    states = allowed if states is None else allowed & set(states)
    query = _items_in(db, job_id, states, None)
    if import_group_id is not None:
        query = query.filter(ImportItem.import_group_id == import_group_id)
    items = query.all()
    for item in items:
        item.state = st.next_item_state(item.state, ItemEvent.SKIP)
        item.error_reason = reason
        remove_staged(job_id, item.staging_key)
        item.staging_key = None
    db.flush()
    recompute_job_status(db, job_id)
    return len(items)


def pause_job(db: Session, job_id: str) -> str:
    job = db.get_one(ImportJob, job_id)
    if job.status == st.JOB_ACTIVE:
        job.status = st.JOB_PAUSED
    return recompute_job_status(db, job_id)


def resume_job(db: Session, job_id: str) -> str:
    job = db.get_one(ImportJob, job_id)
    if job.status == st.JOB_PAUSED:
        job.status = st.JOB_ACTIVE
    return recompute_job_status(db, job_id)


def cancel_job(db: Session, job_id: str) -> int:
    """Stop the job. Finished items are kept; open items are skipped.

    Items currently ``processing`` finish their batch and are kept too.
    """
    job = db.get_one(ImportJob, job_id)
    if job.status != st.JOB_COMPLETED:
        job.status = st.JOB_CANCELLED
        job.completed_at = utcnow()
    return skip_items(db, job_id, "Cancelled")
