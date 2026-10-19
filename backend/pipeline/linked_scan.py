"""Scanning the linked folder (design/library-setup.md §4.3).

A scan lists the folder and compares each file's size and modification time with its
``source_files`` row. Only new and changed files are read, by the ingest worker, so a
scan that finds nothing new reads no file and creates no job.

    walk (no lock) → load the rows (one query) → diff → apply (one write transaction)

Applying the diff:

- **new**: a ``pending`` row and an item, in one import job for the scan;
- **changed**: an image's file gets a **refresh** item in the same job (§4.5,
  ``linked_refresh``), which updates the image in place. Its row keeps the version the
  image was made from until the refresh records what it read, so a refresh that is
  cancelled or lost is offered again by the next scan. Other rows go back to ``pending``;
- **gone**: an image's row gets ``missing_since`` and the image is kept. Rows without an
  image (duplicates, skipped, failed) are deleted: there's nothing to keep;
- **back again** (missing, same size and mtime): ``missing_since`` is cleared.

A missing image takes over a present duplicate of itself if one was recorded. When the
folder isn't there the source is marked offline and nothing else changes.

The job is then sealed like any import, parsing its paths before taking the write lock
again: a first scan of a large folder must not hold the lock for the whole parse.

Scans run one at a time (``LinkedScanner``), at startup, on a timer
(``linked_rescan_minutes``), when the desktop window regains focus, and on demand.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Literal

from sqlalchemy import delete, exists, insert, select, update
from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.models import Image, ImportItem, ImportJob, LibrarySource, SourceFile
from backend.app.models.database import (
    FILE_DUPLICATE,
    FILE_FAILED,
    FILE_IMAGE,
    FILE_PENDING,
    FILE_REMOVED,
    FILE_SKIPPED,
    SOURCE_DETACHED,
    SOURCE_OFFLINE,
    SOURCE_ONLINE,
)
from backend.app.services import ingest_state as st
from backend.app.services.app_settings import get_settings as get_app_settings
from backend.app.services.linked_files import (
    chunks,
    current_source,
    delete_files,
    ensure_source,
    files_by_id,
    open_linked_jobs,
    repoint_to_duplicates,
)
from backend.app.services.originals import (
    LinkedEntry,
    LinkedFolder,
    forget_availability,
    linked_folder,
)
from backend.app.services.shutdown import ShutdownRequested, raise_if_shutting_down

from .error_classifier import KIND_FILE
from .ingest_queue import (
    AUTO,
    BATTLEMAP,
    OVERSIZED_REASON,
    _session,
    apply_plan,
    cancel_job,
    compute_plan,
    create_job,
    kind_for_path,
    utcnow,
    write_session,
)

logger = logging.getLogger(__name__)

# A focus rescan is ignored this soon after the last scan started.
FOCUS_MIN_INTERVAL = 60.0
# How often the rescan timer wakes to read linked_rescan_minutes.
TIMER_WAKE_SECONDS = 60.0
# Rows per bulk INSERT (each row binds a handful of variables).
_INSERT_CHUNK = 2000

ScanReason = Literal["startup", "timer", "focus", "manual"]


# The diff


@dataclass(frozen=True)
class KnownFile:
    """A ``source_files`` row, as the diff needs it."""

    id: int
    rel_key: str
    size: int
    mtime_ns: int
    state: str
    missing: bool


@dataclass
class ScanDiff:
    new: list[LinkedEntry] = field(default_factory=list)
    changed: list[tuple[KnownFile, LinkedEntry]] = field(default_factory=list)
    gone: list[KnownFile] = field(default_factory=list)
    back: list[KnownFile] = field(default_factory=list)
    unchanged: int = 0


def diff_files(found: Iterable[LinkedEntry], known: Iterable[KnownFile]) -> ScanDiff:
    """Compare the walk with the rows, by key. Pure: nothing is read or written.

    ``removed`` rows (their image was removed) are known but otherwise ignored, so the
    file is never offered again, changed or not.
    """
    by_key = {k.rel_key: k for k in known}
    diff = ScanDiff()
    seen: set[str] = set()
    for entry in found:
        row = by_key.get(entry.rel_key)
        if row is None:
            diff.new.append(entry)
            continue
        seen.add(entry.rel_key)
        if row.state == FILE_REMOVED:
            continue
        if (row.size, row.mtime_ns) != (entry.size, entry.mtime_ns):
            diff.changed.append((row, entry))
        elif row.missing:
            diff.back.append(row)
        else:
            diff.unchanged += 1
    diff.gone = [
        row
        for key, row in by_key.items()
        if key not in seen and not row.missing and row.state != FILE_REMOVED
    ]
    return diff


def known_files(db: Session, source_id: int) -> list[KnownFile]:
    """Every row of the source with a path, in one query (no ORM objects: a large
    folder has tens of thousands)."""
    rows = db.execute(
        select(
            SourceFile.id,
            SourceFile.rel_key,
            SourceFile.size,
            SourceFile.mtime_ns,
            SourceFile.state,
            SourceFile.missing_since.isnot(None),
        ).where(SourceFile.source_id == source_id)
    )
    return [KnownFile(*row) for row in rows]


# Applying it


@dataclass
class ScanResult:
    # busy: the library is being purged
    state: Literal["online", "offline", "detached", "not_linked", "busy"]
    new: int = 0  # files queued: new, changed, or left pending without an item
    changed: int = 0
    refresh: int = 0  # of the files queued, edited images' files (§4.5)
    gone: int = 0
    back: int = 0
    moved: int = 0  # missing images that took over a duplicate
    job_id: str | None = None


def _orphan_pending(db: Session, source_id: int) -> list[SourceFile]:
    """Pending rows with no open item (their job was lost, or a scan's limit left them):
    they're queued again."""
    open_item = exists().where(
        ImportItem.source_file_id == SourceFile.id,
        ImportItem.state.in_(st.OPEN_ITEM_STATES),
    )
    return (
        db.query(SourceFile)
        .filter(
            SourceFile.source_id == source_id,
            SourceFile.state == FILE_PENDING,
            ~open_item,
        )
        .order_by(SourceFile.id)
        .all()
    )


def _images_of(db: Session, file_ids: list[int]) -> dict[int, str]:
    """file id → its image's type, for files that are an image's."""
    found: dict[int, str] = {}
    for chunk in chunks(file_ids):
        rows = db.execute(
            select(Image.source_file_id, Image.image_type).where(Image.source_file_id.in_(chunk))
        )
        for file_id, image_type in rows:
            if file_id is not None:
                found[file_id] = image_type or BATTLEMAP
    return found


def _with_open_item(db: Session, file_ids: list[int]) -> set[int]:
    """The files with an item still to be processed."""
    found: set[int] = set()
    for chunk in chunks(file_ids):
        rows = db.scalars(
            select(ImportItem.source_file_id).where(
                ImportItem.source_file_id.in_(chunk),
                ImportItem.state.in_(st.OPEN_ITEM_STATES),
            )
        )
        found.update(file_id for file_id in rows if file_id is not None)
    return found


def apply_diff(
    db: Session, source: LibrarySource, folder: LinkedFolder, diff: ScanDiff, max_new: int
) -> ScanResult:
    """Record the diff and queue what needs reading, in the caller's write transaction."""
    now = utcnow()
    result = ScanResult("online", changed=len(diff.changed), gone=len(diff.gone))
    orphans = {row.id: row for row in _orphan_pending(db, source.id)}
    without_item = set(orphans)
    touched = [k.id for k in diff.gone] + [k.id for k in diff.back]
    # The rows as they are now: the worker may have written some since the snapshot
    fresh = files_by_id(db, touched + [k.id for k, _ in diff.changed])

    forgotten: list[int] = []
    for known in diff.gone:
        row = fresh.get(known.id)
        orphans.pop(known.id, None)
        if row is None:
            continue
        if row.state == FILE_IMAGE and row.missing_since is None:
            row.missing_since = now
        elif row.state in (FILE_DUPLICATE, FILE_SKIPPED, FILE_FAILED):
            forgotten.append(row.id)
        # A pending file fails when its item reads it; a removed one stays removed.

    for known in diff.back:
        row = fresh.get(known.id)
        if row is not None and (row.size, row.mtime_ns) == (known.size, known.mtime_ns):
            row.missing_since = None
            result.back += 1

    # (entry, row to reuse): None makes a new row
    queue: list[tuple[LinkedEntry, SourceFile | None]] = []
    edited = [k.id for k, _ in diff.changed if k.state == FILE_IMAGE]
    image_types = _images_of(db, edited)
    refreshing = _with_open_item(db, edited)
    refresh: dict[int, str] = {}  # file id → its image's type
    for known, entry in diff.changed:
        row = fresh.get(known.id)
        orphans.pop(known.id, None)
        if row is None:  # deleted meanwhile (a move took it): the file is new
            queue.append((entry, None))
        elif row.state == FILE_PENDING:  # its item reads the file as it is then
            row.size, row.mtime_ns = entry.size, entry.mtime_ns
            if row.id in without_item:
                queue.append((entry, row))
        elif row.state == FILE_IMAGE and row.id in image_types:
            # Edited in place: refresh its image (§4.5). The row keeps the version the
            # image was made from until the refresh records the one it read.
            row.missing_since = None
            if row.id not in refreshing:  # an open refresh reads the file as it is then
                refresh[row.id] = image_types[row.id]
                queue.append((entry, row))
        elif row.state != FILE_REMOVED:
            row.state, row.image_id, row.reason = FILE_PENDING, None, None
            row.size, row.mtime_ns, row.content_hash = entry.size, entry.mtime_ns, None
            row.missing_since = None
            queue.append((entry, row))

    # The orphans left are unchanged files (changed and gone ones were handled above)
    queue += [(LinkedEntry(row.rel_key, row.size, row.mtime_ns), row) for row in orphans.values()]
    queue += [(entry, None) for entry in diff.new]

    delete_files(db, forgotten)
    db.flush()
    result.moved = repoint_to_duplicates(db, source.id)

    if len(queue) > max_new:
        logger.warning(
            "Linked scan found %d files to add; adding %d now and the rest next scan",
            len(queue),
            max_new,
        )
        queue = queue[:max_new]
    if queue:
        result.job_id = _queue_files(db, source, folder, queue, refresh)
    result.new = len(queue)
    result.refresh = sum(1 for _, row in queue if row is not None and row.id in refresh)
    source.state = SOURCE_ONLINE
    source.last_scan_at = now
    return result


def _queue_files(
    db: Session,
    source: LibrarySource,
    folder: LinkedFolder,
    queue: list[tuple[LinkedEntry, SourceFile | None]],
    refresh: dict[int, str],
) -> str:
    """One import job for the scan, labelled with the folder's name, with an item per
    file (Auto image type), read where it is. Left unsealed: the caller plans it once the
    paths are parsed, outside the write lock (``seal_scan``).

    ``refresh``: file id → image type, for the edited files of images (§4.5). Their items
    have their image's type, and an oversized one fails without the row leaving its image.

    Rows and items are inserted in bulk: a first scan can add tens of thousands."""
    max_size = get_app_settings(db).max_import_file_size
    job = create_job(db, label=folder.name, default_image_type=AUTO)
    # The job waits while the folder is unavailable, like a local import's.
    job.source_roots = json.dumps([str(folder.root)])
    job.library_source_id = source.id

    file_ids = {entry.rel_key: row.id for entry, row in queue if row is not None}
    new = [
        {
            "source_id": source.id,
            "rel_key": entry.rel_key,
            "size": entry.size,
            "mtime_ns": entry.mtime_ns,
            "state": FILE_PENDING,
        }
        for entry, row in queue
        if row is None
    ]
    for chunk in chunks(new, _INSERT_CHUNK):
        inserted = db.execute(
            insert(SourceFile).returning(SourceFile.id, SourceFile.rel_key), chunk
        )
        file_ids.update({str(rel_key): file_id for file_id, rel_key in inserted})

    items = []
    oversized: list[int] = []
    for entry, row in queue:
        file_id = file_ids[entry.rel_key]
        item = {
            "job_id": job.id,
            "kind": kind_for_path(entry.rel_key) or "image",
            "relative_path": entry.rel_key,
            "filename": PurePosixPath(entry.rel_key).name,
            "size": entry.size,
            "last_modified": entry.mtime_ns // 1_000_000,
            "image_type": refresh.get(file_id, AUTO),
            "state": st.READY,
            "source_path": str(folder.root / entry.rel_key),
            "source_file_id": file_id,
            "error_kind": None,
            "error_stage": None,
            "error_reason": None,
        }
        if entry.size > max_size:  # as a manifest entry would be: failed, not read
            item.update(
                state=st.FAILED,
                error_kind=KIND_FILE,
                error_stage="validate",
                error_reason=OVERSIZED_REASON,
            )
            if row is not None and file_id in refresh:  # the image keeps its file
                row.size, row.mtime_ns, row.reason = entry.size, entry.mtime_ns, OVERSIZED_REASON
            else:
                oversized.append(file_id)
        items.append(item)
    for chunk in chunks(items, _INSERT_CHUNK):
        db.execute(insert(ImportItem), chunk)
    for chunk in chunks(oversized):
        db.execute(
            update(SourceFile)
            .where(SourceFile.id.in_(chunk))
            .values(state=FILE_FAILED, reason=OVERSIZED_REASON)
        )
    logger.info("Linked scan: %d file(s) to add from %s (job %s)", len(items), folder.name, job.id)
    return job.id


def seal_scan(job_id: str) -> None:
    """Seal a scan's job with ``plan_job``'s rules (new files in a known pack join its
    group): parsing happens outside the write lock, the result is written in one short
    transaction."""
    with _session() as db:
        planned = compute_plan(db, job_id)
    with write_session() as db:
        apply_plan(db, job_id, planned)


def _discard_unsealed(db: Session, source_id: int) -> None:
    """A scan's job left unsealed by a crash: delete it, its items and their files' rows,
    so this scan finds those files new again."""
    jobs = [
        job_id
        for (job_id,) in db.query(ImportJob.id).filter(
            ImportJob.library_source_id == source_id, ImportJob.planned_at.is_(None)
        )
    ]
    for job_id in jobs:
        file_ids = [
            file_id
            for (file_id,) in db.query(ImportItem.source_file_id).filter(
                ImportItem.job_id == job_id, ImportItem.source_file_id.isnot(None)
            )
        ]
        db.query(ImportItem).filter(ImportItem.job_id == job_id).delete()
        db.query(ImportJob).filter(ImportJob.id == job_id).delete()
        for chunk in chunks(file_ids):
            db.execute(
                delete(SourceFile).where(SourceFile.id.in_(chunk), SourceFile.state == FILE_PENDING)
            )
        logger.warning("Discarded an unfinished scan's job %s", job_id)


def _purging() -> bool:
    from backend.app.services.job_runner import PURGE_JOB_NAME, get_job_runner

    return get_job_runner().has_active_job(PURGE_JOB_NAME)


def _mark(source_id: int, state: str) -> None:
    with write_session() as db:
        source = db.get(LibrarySource, source_id)
        if source is not None:
            source.state = state


def scan_linked_folder() -> ScanResult:
    """One scan of the configured linked folder. The walk takes no lock; the diff is
    applied in one write transaction. Use ``LinkedScanner``, which runs one at a time."""
    folder = linked_folder()
    if folder is None:
        return ScanResult("not_linked")
    if _purging():
        return ScanResult("busy")
    # Checked before taking the write lock: a stat of an unreachable share can hang.
    available = folder.available()
    with write_session() as db:
        source = ensure_source(db, str(folder.root))
        source_id = source.id
        if source.state == SOURCE_DETACHED:  # "Stop using this folder", until restart
            return ScanResult("detached")
        _discard_unsealed(db, source_id)
        if not available:
            source.state = SOURCE_OFFLINE
            return ScanResult("offline")

    started = time.monotonic()
    found = list(folder.list())
    raise_if_shutting_down()
    # A folder that went while it was listed would look empty: nothing is marked missing.
    if not folder.available():
        _mark(source_id, SOURCE_OFFLINE)
        return ScanResult("offline")
    with _session() as db:
        known = known_files(db, source_id)
    diff = diff_files(found, known)
    listed = time.monotonic() - started

    with write_session() as db:
        source = db.get(LibrarySource, source_id)
        if source is None or _purging():
            return ScanResult("busy")
        if source.state == SOURCE_DETACHED:  # "Stop using this folder" meanwhile
            return ScanResult("detached")
        result = apply_diff(db, source, folder, diff, settings.max_local_import_items)
    if result.job_id is not None:
        seal_scan(result.job_id)
    logger.info(
        "Linked scan of %s: %d files listed in %.1fs; %d to read (%d to refresh), "
        "%d changed, %d gone, %d back, %d moved",
        folder.name,
        len(found),
        listed,
        result.new,
        result.refresh,
        result.changed,
        result.gone,
        result.back,
        result.moved,
    )
    return result


# Startup


def reconcile_linked_source(db: Session) -> None:
    """At startup, after the library check: bring the source row in line with the
    configured folder (§3.3). Commits.

    - A folder is configured: create or update the row; it's online or offline.
      Unfinished scans of a folder that moved now wait on its new place.
    - None is, but a row exists: the source is detached. Its images show as offline,
      and its unfinished scans are cancelled (their files are offered again if it's
      linked again).
    """
    root = settings.linked_library_dir
    source = current_source(db)
    if root is None:
        if source is not None and source.state != SOURCE_DETACHED:
            for job in open_linked_jobs(db, source.id):
                cancel_job(db, job.id)
            source.state = SOURCE_DETACHED
            logger.info("The linked folder %s is no longer configured", source.location)
        db.commit()
        return
    moved = source is not None and source.location != str(root)
    source = ensure_source(db, str(root))
    if moved:
        for job in open_linked_jobs(db, source.id):
            job.source_roots = json.dumps([str(root)])
    source.state = SOURCE_ONLINE if root.is_dir() else SOURCE_OFFLINE
    db.commit()


# Running scans


class LinkedScanner:
    """Runs scans one at a time, on a background thread or the caller's."""

    def __init__(self, scan=scan_linked_folder):
        self._scan = scan
        self._lock = threading.Lock()
        self._running = False
        self._last_started: float | None = None
        self._last_finished: float | None = None

    @property
    def running(self) -> bool:
        return self._running

    def _begin(self) -> bool:
        with self._lock:
            if self._running:
                return False
            self._running = True
            self._last_started = time.monotonic()
            return True

    def _run(self) -> ScanResult | None:
        from .ingest_worker import get_ingest_worker

        try:
            result = self._scan()
        except ShutdownRequested:
            return None
        except Exception:
            logger.exception("Linked folder scan failed")
            return None
        finally:
            with self._lock:
                self._running = False
                self._last_finished = time.monotonic()
            forget_availability()
        worker = get_ingest_worker()
        worker.bump()
        if result.job_id:
            worker.wake()
        return result

    def scan(self) -> ScanResult | None:
        """Scan now, on this thread. None if a scan is already running (or it failed)."""
        return self._run() if self._begin() else None

    def start(self, reason: ScanReason) -> bool:
        """Start a scan on a background thread unless one is running. A ``focus`` scan
        is also skipped within a minute of the last one. Returns whether it started."""
        if reason == "focus" and self.started_within(FOCUS_MIN_INTERVAL):
            return False
        if not self._begin():
            return False
        logger.debug("Linked scan started (%s)", reason)
        threading.Thread(target=self._run, name="linked-scan", daemon=True).start()
        return True

    def started_within(self, seconds: float) -> bool:
        started = self._last_started
        return started is not None and time.monotonic() - started < seconds

    def due(self, minutes: int) -> bool:
        """Whether the timer should scan: rescans are on and the last one finished at
        least ``minutes`` ago."""
        if minutes <= 0 or self._running:
            return False
        finished = self._last_finished
        return finished is None or time.monotonic() - finished >= minutes * 60


_scanner: LinkedScanner | None = None


def get_linked_scanner() -> LinkedScanner:
    global _scanner
    if _scanner is None:
        _scanner = LinkedScanner()
    return _scanner


def _rescan_minutes() -> int:
    with _session() as db:
        return get_app_settings(db).linked_rescan_minutes


async def rescan_timer(wake_seconds: float = TIMER_WAKE_SECONDS) -> None:
    """Scan every ``linked_rescan_minutes`` (0: only at startup). The setting is read at
    each wake, so a change applies without a restart; any scan restarts the interval."""
    scanner = get_linked_scanner()
    while True:
        await asyncio.sleep(wake_seconds)
        try:
            minutes = await asyncio.to_thread(_rescan_minutes)
        except Exception:
            logger.warning("Couldn't read linked_rescan_minutes", exc_info=True)
            continue
        if scanner.due(minutes):
            scanner.start("timer")
