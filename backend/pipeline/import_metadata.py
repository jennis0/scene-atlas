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
it inside the import's write transaction would hold SQLite's lock for minutes. Callers
therefore load after their own transaction, while the job is still unsealed, so nothing
claims its items meanwhile.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TextIO

import numpy as np
from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from backend.app.models import ImportExportEntry, ImportJob, TagCategory
from backend.pipeline import library_format as lf

logger = logging.getLogger(__name__)

_BATCH = 1_000
# A tag the API would refuse is cut to its limit (models/schemas.py TagText)
_TAG_MAX = 100

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
        name = category.name[:_TAG_MAX]
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


def load_export(job_id: str, opener: Opener, where: str = "") -> int:
    """Store the entries of a ``scene-atlas.jsonl`` (``opener`` opens it, and is called
    twice) for the job, in transactions of its own. *where* is the file's folder in the
    import ("" at its root). Returns how many entries were stored; 0, with a note on the
    job, when the file can't be used."""
    where = "" if where in ("", ".") else where
    try:
        header = _header(opener)
    except (lf.FormatError, OSError, UnicodeError) as e:
        note = (
            f"The Scene Atlas metadata in this import couldn't be read ({e}), so its files "
            "were imported without it."
        )
        _note(job_id, note)
        logger.warning("Import %s: metadata not used: %s", job_id, e)
        return 0

    source = uuid.uuid4().hex
    encoder = header.model.encoder_sha256 if header.model else None
    stored = 0
    rows: list[dict] = []

    def flush() -> None:
        nonlocal stored, rows
        if rows:
            batch = rows
            _write(lambda db: db.execute(insert(ImportExportEntry), batch))
            stored, rows = stored + len(batch), []

    with opener() as fp:
        for line in lf.read_lines(fp):
            if not isinstance(line, lf.GroupLine):
                continue
            group = line.group.model_dump_json(exclude_none=True) if line.group else None
            for image in line.images:
                if image.stored_hash is None:
                    continue  # nothing to match it by
                path = f"{where}/{image.path}" if where and image.path else image.path
                rows.append(
                    {
                        "job_id": job_id,
                        "source": source,
                        "stored_hash": image.stored_hash,
                        "encoder": encoder if image.vector else None,
                        "path": path,
                        "image": image.model_dump_json(exclude_none=True),
                        "group_entry": group,
                    }
                )
                if len(rows) >= _BATCH:
                    flush()
    flush()

    def finish(db: Session) -> None:
        _add_categories(db, header.tag_categories)
        job = db.get(ImportJob, job_id)
        if job is not None and job.export_model is None:
            model = header.model.model_dump(exclude_none=True) if header.model else {}
            job.export_model = json.dumps(model)

    _write(finish)
    logger.info("Import %s: %d metadata entries from %s", job_id, stored, where or "its root")
    return stored


def load_exports(job_id: str, files: Iterable[tuple[Opener, str]]) -> int:
    """``load_export`` for each of an import's metadata files, as (opener, folder)."""
    return sum(load_export(job_id, opener, where) for opener, where in files)


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
