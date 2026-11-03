"""Export the library's metadata (design/export-backup-move.md §4).

Writes a gzipped ``library`` file of the ``scene-atlas.jsonl`` format: every group and
image with its tags, grid, hashes, colours and vector, the linked library's rows and the
settings. Not the image files: a rebuild needs the store folder as well.

Runs as a background job. The database is read in one read transaction (``begin_read``),
so the file is a consistent snapshot while imports and edits carry on. It is written to
``<name>.part`` and renamed when complete, so a half-written export is never mistaken for
one.

Vectors are read in one pass over the LanceDB table into a scratch file, packed in the
order they come, with an offset per image id; then they are looked up group by group.
LanceDB has no index on ``id``, so asking it per group would scan the table each time.
Vectors written after the snapshot are of images it doesn't hold, and are ignored.
"""

from __future__ import annotations

import gzip
import logging
import os
import re
import threading
import time
import uuid
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from sqlalchemy import func, select

from backend.app.config import settings
from backend.app.library_identity import get_library_id
from backend.app.models.database import Image, listed_images
from backend.app.services.shutdown import raise_if_shutting_down
from backend.pipeline import library_format as lf
from backend.pipeline.db import pipeline_db
from backend.pipeline.ingest_queue import begin_read

if TYPE_CHECKING:
    from backend.app.services.lancedb_service import LanceDBService

logger = logging.getLogger(__name__)

JOB_NAME = "Exporting metadata"
# The names the server writes, and the only ones it serves back.
EXPORT_NAME = re.compile(r"scene-atlas-metadata-[0-9]{8}-[0-9]{6}\.jsonl\.gz")
# A finished export waits this long in the exports folder to be downloaded.
KEEP_SECONDS = 24 * 3600

ProgressFn = Callable[[int, int, str | None], None]

# Held while deciding to start an export and while cleaning the exports folder, so a
# clean can't delete the partial files of an export being started.
export_lock = threading.Lock()


def export_name(now: datetime | None = None) -> str:
    """The file name for an export made *now*: ``scene-atlas-metadata-<date>-<time>.jsonl.gz``."""
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%d-%H%M%S")
    return f"scene-atlas-metadata-{stamp}.jsonl.gz"


def is_export_name(name: str) -> bool:
    return EXPORT_NAME.fullmatch(name) is not None


def latest_export(folder: Path | None = None) -> Path | None:
    """The newest finished export in the exports folder, if any."""
    folder = folder or settings.metadata_exports_dir
    if not folder.is_dir():
        return None
    names = sorted(p.name for p in folder.iterdir() if is_export_name(p.name))
    return folder / names[-1] if names else None


def clean_exports(folder: Path | None = None, keep_seconds: float = KEEP_SECONDS) -> int:
    """Delete what a download or a crash left in the exports folder: partial files and
    scratch vectors always, finished exports once older than *keep_seconds*. Returns how
    many files went. Call it only while no export is running: it would delete that
    export's partial files."""
    folder = folder or settings.metadata_exports_dir
    if not folder.is_dir():
        return 0
    cutoff = time.time() - keep_seconds
    removed = 0
    for path in folder.iterdir():
        try:
            stale = path.suffix in (".part", ".vectors") or (
                is_export_name(path.name) and path.stat().st_mtime < cutoff
            )
            if stale and path.is_file():
                path.unlink()
                removed += 1
        except OSError as e:
            logger.warning("Could not remove %s: %s", path, e)
    return removed


def clean_exports_when_idle() -> int:
    """``clean_exports``, unless an export is running (scheduled hourly)."""
    from backend.app.services.job_runner import get_job_runner

    with export_lock:
        if get_job_runner().has_active_job(JOB_NAME):
            return 0
        return clean_exports()


def _model_info(svc: LanceDBService) -> dict:
    """The active model, as the header records it: the one whose table *svc* is."""
    from backend.app.services.clip_service import get_effective_model_name
    from backend.app.services.image_type_classifier import vision_encoder_sha256
    from backend.app.services.model_download_service import get_model_dir

    name = get_effective_model_name()
    return {
        "name": name,
        "encoder_sha256": vision_encoder_sha256(get_model_dir(name)),
        "dim": svc.vector_size,
    }


@contextmanager
def _vector_lookup(svc: LanceDBService, max_id: int, scratch: Path) -> Iterator[lf.VectorLookup]:
    """Read every vector once into *scratch*, then look them up by id. The file holds
    only the vectors there are (packed), plus 8 bytes per id in memory for their offsets.
    It is closed before it is deleted (Windows requires it)."""
    row_bytes = svc.vector_size * 4
    offsets = np.full(max_id + 1, -1, dtype=np.int64)
    try:
        with scratch.open("w+b") as fp:
            for ids, batch in svc.iter_vectors():
                keep = (ids >= 0) & (ids <= max_id)
                ids, batch = ids[keep], batch[keep].astype("<f4")
                offsets[ids] = fp.tell() + np.arange(len(ids), dtype=np.int64) * row_bytes
                fp.write(batch.tobytes())
            fp.flush()

            def lookup(image_ids: Sequence[int]) -> dict[int, np.ndarray]:
                found = {}
                for image_id in image_ids:
                    if 0 <= image_id <= max_id and offsets[image_id] >= 0:
                        fp.seek(int(offsets[image_id]))
                        found[image_id] = np.frombuffer(fp.read(row_bytes), dtype="<f4")
                return found

            yield lookup
    finally:
        scratch.unlink(missing_ok=True)


def export_metadata(target: Path, progress_fn: ProgressFn | None = None) -> dict:
    """Write the library's metadata to *target* (``.jsonl.gz``). Returns the file's
    ``path``, ``name`` and size in ``bytes``, and how many ``images`` it holds.

    Fails, leaving no file, if the vectors can't be read: an export never leaves them
    out silently."""
    from backend.app.services.lancedb_service import get_lancedb_service

    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".part")
    scratch_dir = settings.metadata_exports_dir
    scratch_dir.mkdir(parents=True, exist_ok=True)
    scratch = scratch_dir / f"{uuid.uuid4().hex}.vectors"
    svc = get_lancedb_service()  # once: the header and the vectors are the same table's
    done = 0

    def on_group(line: lf.GroupLine) -> None:
        nonlocal done
        raise_if_shutting_down()
        done += len(line.images)
        if progress_fn:
            progress_fn(done, total, f"Exported {done:,} of {total:,} images")

    try:
        with pipeline_db() as db:
            begin_read(db)  # one snapshot from here on
            total, max_id = db.execute(
                select(func.count(Image.id), func.max(Image.id)).where(listed_images())
            ).one()
            with (
                _vector_lookup(svc, max_id or 0, scratch) as vectors,
                gzip.open(part, "wt", encoding="utf-8", compresslevel=6) as out,
            ):
                for text in lf.library_lines(
                    db,
                    app_version=settings.app_version,
                    library_id=get_library_id(db),
                    model=_model_info(svc),
                    vectors=vectors,
                    on_group=on_group,
                ):
                    out.write(text)
        os.replace(part, target)
    finally:
        part.unlink(missing_ok=True)
    size = target.stat().st_size
    logger.info("Metadata export: %d images, %d bytes -> %s", done, size, target)
    return {"path": str(target), "name": target.name, "images": done, "bytes": size}
