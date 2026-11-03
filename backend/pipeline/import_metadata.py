"""Scene Atlas metadata that comes with an import (design/export-backup-move.md §6).

A zip or folder in the readable layout carries a ``scene-atlas.jsonl``. When an import
finds one (``ingest_archive``, ``ingest_local``, or the browser's upload of it before the
seal), ``load_export`` validates it and stores each image entry against the job, keyed by
the hash of the file it describes. The worker then matches each file of the job, once it
has decoded it and knows its hash (``match_exports``): a matched file imports with its
entry's type, name, grid, tags and (when it fits the installed model) vector, and the
grouping phase puts it in its entry's group by ``uid``.

The metadata never fails an import: a file that doesn't validate is ignored, with a note
on the job for its report, and the files import as they would without it.

``load_export`` reads the file twice: once to validate all of it (so a bad file stores
nothing, and leaves the job's other metadata files alone), then to store it in batches,
each in a short write transaction of its own. A full export's file is a gigabyte; reading
it inside the import's write transaction would hold SQLite's lock for minutes, and a
request that waited for it would outlast a proxy's timeout.

So callers record their files on the job (``add_pending``, in their own transaction, so
the record and the items commit together), then ``kick`` the loader: one thread, loading
one file at a time. The worker claims none of the items of a job with metadata pending
(``ingest_queue._claimable_jobs``), so a seal can come at any time: its files wait. The
record is in the database, so a restart carries on (``recover_pending``): a file's rows
have a ``source`` made from the job and its path, and a load first deletes any left by an
interrupted one. A load that fails part way deletes what it stored.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
import uuid
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TextIO

import numpy as np
from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from backend.app.models import ImportExportEntry, ImportJob, TagCategory
from backend.app.models.schemas import TAG_MAX_LENGTH
from backend.pipeline import library_format as lf

logger = logging.getLogger(__name__)

_BATCH = 1_000

Opener = Callable[[], TextIO]


def is_metadata_file(path: str) -> bool:
    """Whether *path* names a ``scene-atlas.jsonl``, at any depth."""
    return PurePosixPath(path).name == lf.FILENAME


def file_opener(path: Path) -> Opener:
    return lambda: lf.open_file(path)


@dataclass(frozen=True)
class ExportMatch:
    """A file's entry: what it imports with."""

    image: lf.ImageEntry
    group: lf.GroupEntry | None
    vector: np.ndarray | None


def _installed_model() -> tuple[str | None, int | None]:
    """The installed encoder's hash and the vector table's size: an entry's vector fits
    when it is from that encoder and of that size."""
    from backend.app.services.clip_service import get_effective_model_name
    from backend.app.services.image_type_classifier import vision_encoder_sha256
    from backend.app.services.lancedb_service import get_lancedb_service
    from backend.app.services.model_download_service import get_model_dir

    try:
        dim = get_lancedb_service().vector_size
    except Exception:
        return None, None
    return vision_encoder_sha256(get_model_dir(get_effective_model_name())), dim


def _add_categories(db: Session, categories: Sequence[lf.TagCategoryEntry]) -> None:
    """Create the file's tag categories the library doesn't have; never change one it has."""
    have = set(db.scalars(select(TagCategory.name)))
    for category in categories:
        name = category.name[:TAG_MAX_LENGTH]
        if name in have:
            continue
        values = [
            v.model_dump(exclude_none=True) if isinstance(v, lf.CommonValue) else v
            for v in category.common_values
        ]
        db.add(
            TagCategory(
                name=name,
                description=category.description,
                color=category.color,
                icon=category.icon,
                common_values=json.dumps(values) if values else None,
                display_order=category.display_order,
            )
        )
        have.add(name)
    db.flush()


def _write(fn: Callable[[Session], object]) -> None:
    from backend.pipeline.ingest_queue import write_session

    with write_session() as db:
        fn(db)


def _note(job_id: str, note: str) -> None:
    def write(db: Session) -> None:
        job = db.get(ImportJob, job_id)
        if job is not None:
            job.export_note = note

    _write(write)


class _JobGone(Exception):
    """The job was deleted, or grouped, while its metadata loaded."""


# The pending files: a JSON list on the job of {"path", "ready", "delete"}. A file that is
# still arriving (the browser's upload) is not ready; "delete" for staging copies.


def _pending(job: ImportJob) -> list[dict]:
    return json.loads(job.metadata_pending) if job.metadata_pending else []


def _set_pending(job: ImportJob, entries: list[dict]) -> None:
    job.metadata_pending = json.dumps(entries) if entries else None


def add_pending(
    db: Session, job: ImportJob, paths: Sequence[Path], *, ready: bool = True, delete: bool = True
) -> None:
    """Record metadata files to load for the job, in the caller's transaction; ``kick``
    the loader once it commits. *delete*: they're staging copies, deleted once loaded."""
    if paths:
        new = [{"path": str(p), "ready": ready, "delete": delete} for p in paths]
        _set_pending(job, _pending(job) + new)


def _change_pending(db: Session, job_id: str, path: str, *, ready: bool | None) -> None:
    """Mark the file ready (``ready=True``), or forget it (``ready=None``)."""
    job = db.get(ImportJob, job_id)
    if job is None:
        return
    entries = _pending(job)
    if ready is None:
        entries = [e for e in entries if e["path"] != path]
    else:
        for e in entries:
            if e["path"] == path:
                e["ready"] = ready
    _set_pending(job, entries)


def set_ready(job_id: str, path: Path) -> None:
    _write(lambda db: _change_pending(db, job_id, str(path), ready=True))


def forget_pending(job_id: str, path: Path) -> None:
    _write(lambda db: _change_pending(db, job_id, str(path), ready=None))


def pending_paths(db: Session) -> set[tuple[str, str]]:
    """(job id, file name) of every pending file (the stray-staging sweep spares them)."""
    out = set()
    for job_id, raw in db.execute(
        select(ImportJob.id, ImportJob.metadata_pending).where(
            ImportJob.metadata_pending.isnot(None)
        )
    ):
        out |= {(job_id, Path(e["path"]).name) for e in json.loads(raw or "[]")}
    return out


def recover_pending() -> None:
    """At startup: a file that was still arriving when the backend stopped is incomplete;
    forget it (the browser sends it again). Loads that were interrupted are carried on."""

    def recover(db: Session) -> None:
        for job in db.scalars(select(ImportJob).where(ImportJob.metadata_pending.isnot(None))):
            entries = _pending(job)
            for e in entries:
                if not e["ready"]:
                    Path(e["path"]).unlink(missing_ok=True)
            _set_pending(job, [e for e in entries if e["ready"]])

    _write(recover)
    kick()


def _next_load() -> tuple[str, dict] | None:
    from backend.pipeline.db import pipeline_db

    with pipeline_db() as db:
        rows = db.execute(
            select(ImportJob.id, ImportJob.metadata_pending)
            .where(ImportJob.metadata_pending.isnot(None))
            .order_by(ImportJob.created_at, ImportJob.id)
        ).all()
    for job_id, raw in rows:
        ready = [e for e in json.loads(raw or "[]") if e["ready"]]
        if ready:
            return job_id, ready[0]
    return None


def _source(job_id: str, path: str) -> str:
    return hashlib.sha256(f"{job_id}\0{path}".encode()).hexdigest()[:32]


def _load_pending(job_id: str, entry: dict) -> None:
    path = Path(entry["path"])
    try:
        load_export(job_id, file_opener(path), source=_source(job_id, entry["path"]))
    except Exception:
        # Only the cleanup after a failure gets here (a busy database): the job must not
        # wait on this file for ever
        logger.exception("Import %s: loading its metadata failed", job_id)
    finally:
        try:
            forget_pending(job_id, path)
        finally:
            if entry.get("delete"):
                path.unlink(missing_ok=True)
    from backend.pipeline.ingest_worker import get_ingest_worker

    get_ingest_worker().wake()


class _Loader:
    """The one thread that loads metadata files, oldest job first."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self.busy = False

    def kick(self) -> None:
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(
                    target=self._run, name="metadata-loader", daemon=True
                )
                self._thread.start()
        self._wake.set()

    def _run(self) -> None:
        while True:
            self._wake.clear()
            try:
                work = _next_load()
                if work is not None:
                    self.busy = True
                    _load_pending(*work)
                    continue
            except Exception:
                logger.exception("Metadata loader failed; trying again shortly")
                time.sleep(5)
            finally:
                self.busy = False
            self._wake.wait(60)  # a fallback: callers kick it


_loader = _Loader()


def kick() -> None:
    """Load the pending metadata files (after the transaction that recorded them)."""
    _loader.kick()


def wait_for_loads(timeout: float = 60.0) -> bool:
    """Wait until no metadata file is pending (tests, the worker's ``drain``)."""
    from backend.pipeline.db import pipeline_db

    kick()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with pipeline_db() as db:
            waiting = db.scalar(
                select(ImportJob.id).where(ImportJob.metadata_pending.isnot(None)).limit(1)
            )
        if waiting is None:
            return True
        time.sleep(0.02)
    return False


def _header(opener: Opener) -> lf.Header:
    """Validate the whole file (raises ``FormatError``); its header."""
    with opener() as fp:
        lines = lf.read_lines(fp)
        header = next(lines)
        for _ in lines:
            pass
    if not isinstance(header, lf.Header):  # read_lines yields the header first
        raise lf.FormatError(1, "no header")
    return header


def _unusable(job_id: str, e: Exception) -> int:
    note = (
        f"The Scene Atlas metadata in this import couldn't be read ({e}), so its files "
        "were imported without it."
    )
    _note(job_id, note)
    logger.warning("Import %s: metadata not used: %s", job_id, e)
    return 0


def load_export(job_id: str, opener: Opener, *, source: str | None = None) -> int:
    """Store the entries of a ``scene-atlas.jsonl`` (``opener`` opens it, and is called
    twice) for the job, in transactions of its own. Returns how many entries were stored;
    0, with a note on the job, when the file can't be used (nothing of it is kept).
    *source* names its rows; rows of that name already there (an interrupted load) go."""
    try:
        header = _header(opener)
    except Exception as e:  # a corrupt gzip raises zlib.error or EOFError, not OSError
        return _unusable(job_id, e)

    source = source or uuid.uuid4().hex
    _write(
        lambda db: db.execute(delete(ImportExportEntry).where(ImportExportEntry.source == source))
    )
    encoder = header.model.encoder_sha256 if header.model else None
    stored = 0
    rows: list[dict] = []

    def insert_rows(db: Session, batch: list[dict]) -> None:
        if db.get(ImportJob, job_id) is None:
            raise _JobGone
        db.execute(insert(ImportExportEntry), batch)

    def flush() -> None:
        nonlocal stored, rows
        if rows:
            batch = rows
            _write(lambda db: insert_rows(db, batch))
            stored, rows = stored + len(batch), []

    def finish(db: Session) -> None:
        job = db.get(ImportJob, job_id)
        if job is None or job.grouped_at is not None:  # grouped: too late to be used
            raise _JobGone
        _add_categories(db, header.tag_categories)
        if job.export_model is None:
            model = header.model.model_dump(exclude_none=True) if header.model else {}
            job.export_model = json.dumps(model)

    try:
        with opener() as fp:
            for line in lf.read_lines(fp):
                if not isinstance(line, lf.GroupLine):
                    continue
                group = line.group.model_dump_json(exclude_none=True) if line.group else None
                for image in line.images:
                    if image.stored_hash is None:
                        continue  # nothing to match it by
                    rows.append(
                        {
                            "job_id": job_id,
                            "source": source,
                            "stored_hash": image.stored_hash,
                            "encoder": encoder if image.vector else None,
                            "path": image.path,
                            "image": image.model_dump_json(exclude_none=True),
                            "group_entry": group,
                        }
                    )
                    if len(rows) >= _BATCH:
                        flush()
        flush()
        _write(finish)
    except Exception as e:
        # Changed since it was validated (a local file, edited), a busy database, the job
        # deleted: what was stored of it goes
        _write(
            lambda db: db.execute(
                delete(ImportExportEntry).where(ImportExportEntry.source == source)
            )
        )
        if isinstance(e, _JobGone):
            logger.info("Import %s: deleted or grouped while its metadata loaded", job_id)
            return 0
        return _unusable(job_id, e)
    logger.info("Import %s: %d metadata entries", job_id, stored)
    return stored


def match_exports(
    db: Session, job_id: str, files: Sequence[tuple[int, str, str]]
) -> dict[int, ExportMatch]:
    """The entries of *files* (item id, hash of its bytes, file name), by item id. A hash
    with several entries (the same bytes as two images) takes the one whose file name
    matches, else the first. A vector is kept only when it is from the installed encoder
    and of the table's size, checked now: the model may have changed since the load."""
    job = db.get(ImportJob, job_id)
    if job is None or job.export_model is None or not files:
        return {}
    encoder, dim = _installed_model()
    hashes = sorted({h for _, h, _ in files})
    by_hash: dict[str, list[ImportExportEntry]] = {}
    for start in range(0, len(hashes), _BATCH):
        query = select(ImportExportEntry).where(
            ImportExportEntry.job_id == job_id,
            ImportExportEntry.stored_hash.in_(hashes[start : start + _BATCH]),
        )
        for entry in db.scalars(query.order_by(ImportExportEntry.id)):
            by_hash.setdefault(entry.stored_hash, []).append(entry)
    matches: dict[int, ExportMatch] = {}
    for item_id, digest, filename in files:
        candidates = by_hash.get(digest)
        if not candidates:
            continue
        named = [c for c in candidates if c.path and PurePosixPath(c.path).name == filename]
        entry = (named or candidates)[0]
        image = lf.ImageEntry.model_validate_json(entry.image)
        vector = None
        if image.vector and encoder and dim and entry.encoder == encoder:
            try:
                vector = lf.decode_vector(image.vector, dim)
            except ValueError:
                vector = None
        group = lf.GroupEntry.model_validate_json(entry.group_entry) if entry.group_entry else None
        matches[item_id] = ExportMatch(image, group, vector)
    return matches


def delete_entries(db: Session, job_ids: Iterable[str]) -> None:
    """Forget the metadata of jobs: deleted, or grouped (the entries are about 6 KB each,
    vector included, and are only needed until then)."""
    ids = list(job_ids)
    if ids:
        db.execute(delete(ImportExportEntry).where(ImportExportEntry.job_id.in_(ids)))
