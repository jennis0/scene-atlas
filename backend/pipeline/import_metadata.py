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
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath

import numpy as np
from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from backend.app.models import ImportExportEntry, ImportJob, TagCategory
from backend.pipeline import library_format as lf

logger = logging.getLogger(__name__)

_BATCH = 1_000


def is_metadata_file(path: str) -> bool:
    """Whether *path* names a ``scene-atlas.jsonl``."""
    return PurePosixPath(path).name == lf.FILENAME


@dataclass(frozen=True)
class ExportMatch:
    """A file's entry: what it imports with."""

    image: lf.ImageEntry
    group: lf.GroupEntry | None
    vector: np.ndarray | None


def _installed_model() -> tuple[str | None, int | None]:
    """The installed encoder's hash and the vector table's size: vectors fit when both
    match the file's header."""
    from backend.app.services.clip_service import get_effective_model_name
    from backend.app.services.image_type_classifier import vision_encoder_sha256
    from backend.app.services.lancedb_service import get_lancedb_service
    from backend.app.services.model_download_service import get_model_dir

    try:
        dim = get_lancedb_service().vector_size
    except Exception:
        return None, None
    return vision_encoder_sha256(get_model_dir(get_effective_model_name())), dim


def _vectors_fit(model: lf.ModelInfo | None) -> bool:
    if model is None or model.encoder_sha256 is None:
        return False
    sha, dim = _installed_model()
    return sha == model.encoder_sha256 and dim == model.dim


def _add_categories(db: Session, categories: Sequence[lf.TagCategoryEntry]) -> None:
    """Create the file's tag categories the library doesn't have; never change one it has."""
    have = set(db.scalars(select(TagCategory.name)))
    for category in categories:
        if category.name in have:
            continue
        values = [
            v.model_dump(exclude_none=True) if isinstance(v, lf.CommonValue) else v
            for v in category.common_values
        ]
        db.add(
            TagCategory(
                name=category.name,
                description=category.description,
                color=category.color,
                icon=category.icon,
                common_values=json.dumps(values) if values else None,
                display_order=category.display_order,
            )
        )
        have.add(category.name)
    db.flush()


def load_export(db: Session, job: ImportJob, lines: Iterable[str], where: str = "") -> int:
    """Store the entries of a ``scene-atlas.jsonl`` (its *lines*) for *job*, in the
    caller's transaction. *where* is the file's folder in the import ("" at its root):
    entries' paths are kept relative to the import. Returns how many entries were stored;
    0, with a note on the job, when the file can't be used."""
    where = "" if where in ("", ".") else where
    rows: list[dict] = []
    stored = 0
    try:
        reader = lf.read_lines(lines)
        header = next(reader)
        if not isinstance(header, lf.Header):  # read_lines yields the header first
            raise lf.FormatError(1, "no header")
        for line in reader:
            if not isinstance(line, lf.GroupLine):
                continue
            group = line.group.model_dump_json(exclude_none=True) if line.group else None
            for image in line.images:
                if image.stored_hash is None:
                    continue  # nothing to match it by
                path = f"{where}/{image.path}" if where and image.path else image.path
                rows.append(
                    {
                        "job_id": job.id,
                        "stored_hash": image.stored_hash,
                        "path": path,
                        "image": image.model_dump_json(exclude_none=True),
                        "group_entry": group,
                    }
                )
                if len(rows) >= _BATCH:
                    db.execute(insert(ImportExportEntry), rows)
                    stored, rows = stored + len(rows), []
        if rows:
            db.execute(insert(ImportExportEntry), rows)
            stored += len(rows)
    except lf.FormatError as e:
        db.execute(delete(ImportExportEntry).where(ImportExportEntry.job_id == job.id))
        job.export_note = (
            f"The Scene Atlas metadata in this import couldn't be read ({e}), so its files "
            "were imported without it."
        )
        logger.warning("Import %s: metadata not used: %s", job.id, e)
        return 0
    _add_categories(db, header.tag_categories)
    model = header.model.model_dump(exclude_none=True) if header.model else {}
    job.export_model = json.dumps({**model, "vectors": _vectors_fit(header.model)})
    logger.info("Import %s: %d metadata entries from %s", job.id, stored, where or "its root")
    return stored


def match_exports(
    db: Session, job_id: str, files: Sequence[tuple[int, str, str]]
) -> dict[int, ExportMatch]:
    """The entries of *files* (item id, hash of its bytes, file name), by item id. A hash
    with several entries (the same bytes as two images) takes the one whose file name
    matches, else the first."""
    job = db.get(ImportJob, job_id)
    if job is None or job.export_model is None or not files:
        return {}
    model = json.loads(job.export_model)
    dim = model.get("dim") if model.get("vectors") else None
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
        if dim and image.vector:
            try:
                vector = lf.decode_vector(image.vector, dim)
            except ValueError:
                vector = None
        group = lf.GroupEntry.model_validate_json(entry.group_entry) if entry.group_entry else None
        matches[item_id] = ExportMatch(image, group, vector)
    return matches


def delete_entries(db: Session, job_ids: Iterable[str]) -> None:
    """Forget the metadata of jobs being deleted."""
    ids = list(job_ids)
    if ids:
        db.execute(delete(ImportExportEntry).where(ImportExportEntry.job_id.in_(ids)))
