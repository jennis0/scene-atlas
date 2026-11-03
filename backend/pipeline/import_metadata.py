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

So callers hand their files to ``load_in_background`` after their own transaction. It
marks the job as loading before it returns, and the worker claims none of a loading job's
items (``loading_jobs``), so a seal can come at any time: the job's files wait for their
metadata. A load that fails part way deletes what it stored (its rows share a ``source``).
A restart mid-load loses the mark, and the files import with what had been stored.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from collections import Counter
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
    """The job was deleted while its metadata loaded."""


# Jobs whose metadata is loading, with how many loads each: the worker leaves them be
_loading: Counter[str] = Counter()
_loading_lock = threading.Lock()
_idle = threading.Condition(_loading_lock)


def loading_jobs() -> set[str]:
    with _loading_lock:
        return set(_loading)


def wait_for_loads(timeout: float = 60.0) -> bool:
    """Wait until no metadata is loading (tests, the worker's ``drain``)."""
    with _idle:
        return _idle.wait_for(lambda: not _loading, timeout)


def load_in_background(job_id: str, files: Sequence[Path], *, delete: Sequence[Path] = ()) -> None:
    """Load *files* for the job in a thread of their own, then delete *delete* (staging
    copies). The job counts as loading from before this returns until the load is done."""
    if not files:
        for path in delete:
            path.unlink(missing_ok=True)
        return
    with _loading_lock:
        _loading[job_id] += 1

    def run() -> None:
        try:
            load_exports(job_id, [file_opener(path) for path in files])
        except Exception:
            logger.exception("Import %s: loading its metadata failed", job_id)
        finally:
            for path in delete:
                path.unlink(missing_ok=True)
            with _idle:
                _loading[job_id] -= 1
                if _loading[job_id] <= 0:
                    del _loading[job_id]
                _idle.notify_all()
            from backend.pipeline.ingest_worker import get_ingest_worker

            get_ingest_worker().wake()

    threading.Thread(target=run, name=f"metadata-{job_id[:8]}", daemon=True).start()


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


def load_export(job_id: str, opener: Opener) -> int:
    """Store the entries of a ``scene-atlas.jsonl`` (``opener`` opens it, and is called
    twice) for the job, in transactions of its own. Returns how many entries were stored;
    0, with a note on the job, when the file can't be used (nothing of it is kept)."""
    try:
        header = _header(opener)
    except Exception as e:  # a corrupt gzip raises zlib.error or EOFError, not OSError
        return _unusable(job_id, e)

    source = uuid.uuid4().hex
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
        if job is None:
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
            logger.info("Import %s: deleted while its metadata loaded", job_id)
            return 0
        return _unusable(job_id, e)
    logger.info("Import %s: %d metadata entries", job_id, stored)
    return stored


def load_exports(job_id: str, openers: Iterable[Opener]) -> int:
    """``load_export`` for each of an import's metadata files."""
    return sum(load_export(job_id, opener) for opener in openers)


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
