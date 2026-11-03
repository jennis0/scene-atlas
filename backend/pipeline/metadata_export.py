"""Export the library's metadata (design/export-backup-move.md §4).

Writes a gzipped ``library`` file of the ``scene-atlas.jsonl`` format: every group and
image with its tags, grid, hashes, colours and vector, the linked library's rows and the
settings. Not the image files: a rebuild needs the store folder as well.

Runs as a background job. The database is read in one transaction, so the file is a
consistent snapshot while imports and edits carry on. It is written to ``<name>.part``
and renamed when complete, so a half-written export is never mistaken for one.

Vectors are read in one pass over the LanceDB table into a scratch file, at an offset per
image id, then looked up group by group. LanceDB has no index on ``id``, so asking it per group
would scan the table once per group.
"""

from __future__ import annotations

import gzip
import logging
import os
import re
import time
import uuid
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager, nullcontext
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from sqlalchemy import func, select

from backend.app.config import settings
from backend.app.library_identity import get_library_id
from backend.app.models.database import Image, listed_images
from backend.app.services.shutdown import raise_if_shutting_down
from backend.pipeline import library_format as lf
from backend.pipeline.db import pipeline_db

logger = logging.getLogger(__name__)

JOB_NAME = "Exporting metadata"
# The names the server writes, and the only ones it serves back.
EXPORT_NAME = re.compile(r"^scene-atlas-metadata-\d{8}-\d{6}\.jsonl\.gz$")
# A finished export waits this long in the exports folder to be downloaded.
KEEP_SECONDS = 24 * 3600

ProgressFn = Callable[[int, int, str | None], None]


def export_name(now: datetime | None = None) -> str:
    """The file name for an export made *now*: ``scene-atlas-metadata-<date>-<time>.jsonl.gz``."""
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%d-%H%M%S")
    return f"scene-atlas-metadata-{stamp}.jsonl.gz"


def clean_exports(folder: Path | None = None, keep_seconds: float = KEEP_SECONDS) -> int:
    """Delete what a download or a crash left in the exports folder: partial files and
    scratch vectors always, finished exports once older than *keep_seconds*. Returns how
    many files went."""
    folder = folder or settings.metadata_exports_dir
    if not folder.is_dir():
        return 0
    cutoff = time.time() - keep_seconds
    removed = 0
    for path in folder.iterdir():
        stale = path.suffix in (".part", ".vectors") or (
            EXPORT_NAME.match(path.name) is not None and path.stat().st_mtime < cutoff
        )
        if stale and path.is_file():
            path.unlink(missing_ok=True)
            removed += 1
    return removed


def _model_info() -> dict | None:
    """The active model, as the header records it, or None when no vectors table is
    available (no model installed yet)."""
    from backend.app.services.clip_service import get_effective_model_name
    from backend.app.services.image_type_classifier import vision_encoder_sha256
    from backend.app.services.lancedb_service import get_lancedb_service
    from backend.app.services.model_download_service import get_model_dir

    try:
        svc = get_lancedb_service()
    except Exception:
        logger.warning("Metadata export: no vectors table; exporting without vectors")
        return None
    name = get_effective_model_name()
    return {
        "name": name,
        "encoder_sha256": vision_encoder_sha256(get_model_dir(name)),
        "dim": svc.vector_size,
    }


@contextmanager
def _vector_lookup(max_id: int, dim: int, scratch: Path) -> Iterator[lf.VectorLookup]:
    """Read every vector once into *scratch*, at a fixed offset per image id, then look
    them up by seeking. The file is closed before it is deleted (Windows requires it)."""
    from backend.app.services.lancedb_service import get_lancedb_service

    rows = max_id + 1
    row_bytes = dim * 4
    present = np.zeros(rows, dtype=bool)
    try:
        with scratch.open("w+b") as fp:
            fp.truncate(rows * row_bytes)
            for ids, batch in get_lancedb_service().iter_vectors():
                for image_id, vector in zip(ids.tolist(), batch.astype("<f4"), strict=True):
                    if 0 <= image_id < rows:
                        fp.seek(image_id * row_bytes)
                        fp.write(vector.tobytes())
                        present[image_id] = True

            def lookup(image_ids: Sequence[int]) -> dict[int, np.ndarray]:
                found = {}
                for image_id in image_ids:
                    if 0 <= image_id < rows and present[image_id]:
                        fp.seek(image_id * row_bytes)
                        found[image_id] = np.frombuffer(fp.read(row_bytes), dtype="<f4")
                return found

            yield lookup
    finally:
        scratch.unlink(missing_ok=True)


def export_metadata(target: Path, progress_fn: ProgressFn | None = None) -> dict:
    """Write the library's metadata to *target* (``.jsonl.gz``). Returns the file's
    ``path``, ``name`` and size in ``bytes``, and how many ``images`` it holds."""
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".part")
    scratch_dir = settings.metadata_exports_dir
    scratch_dir.mkdir(parents=True, exist_ok=True)
    scratch = scratch_dir / f"{uuid.uuid4().hex}.vectors"
    model = _model_info()
    try:
        with pipeline_db() as db:
            # One transaction from here on: the file is a snapshot of one moment.
            total, max_id = db.execute(
                select(func.count(Image.id), func.max(Image.id)).where(listed_images())
            ).one()
            header = lf.header_line(
                db,
                kind=lf.KIND_LIBRARY,
                app_version=settings.app_version,
                library_id=get_library_id(db),
                model=model,
            )
            lookup = _vector_lookup(max_id or 0, model["dim"], scratch) if model else nullcontext()
            with lookup as vectors, gzip.open(part, "wt", encoding="utf-8", compresslevel=6) as out:
                out.write(lf.dump_line(header))
                done = 0
                for line in lf.group_lines(db, kind=lf.KIND_LIBRARY, vectors=vectors):
                    raise_if_shutting_down()
                    out.write(lf.dump_line(line))
                    done += len(line["images"])
                    if progress_fn:
                        progress_fn(done, total, f"Exported {done:,} of {total:,} images")
                for line in lf.source_file_lines(db):
                    out.write(lf.dump_line(line))
        os.replace(part, target)
    finally:
        part.unlink(missing_ok=True)
    size = target.stat().st_size
    logger.info("Metadata export: %d images, %d bytes -> %s", done, size, target)
    return {"path": str(target), "name": target.name, "images": done, "bytes": size}
