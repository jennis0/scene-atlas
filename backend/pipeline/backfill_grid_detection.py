"""Run grid detection (v3) on existing battlemap images.

Which images are analysed (``detection_mode``):
- no grid information -> presence and size
- file name says gridded but gives no size -> size only
- previously detected -> re-detected only with ``force``
Never touched: grids set by hand, and file names that say "no grid" or give an exact
NxM; those were the most reliable labels in evaluation (design/grid-detection-v3.md).

Memory is reserved from the shared ingest budget, so this can run alongside imports.

Usage:
    uv run python -m backend.pipeline.backfill_grid_detection [--force]
"""

import logging

from PIL import Image as PILImage
from sqlalchemy import and_, or_

from backend.app.config import settings
from backend.app.models.database import (
    GRID_SOURCE_DETECTOR,
    GRID_SOURCE_FILENAME,
    GRID_SOURCE_USER,
    Image,
    get_engine,
    get_session_local,
)
from backend.app.services import get_image_store
from backend.app.services.memory_budget import get_memory_budget
from backend.pipeline.ingest_process import grid_detection_bytes
from backend.pipeline.pipeline_config import PipelineConfig, load_pipeline_config
from backend.pipeline.tasks.grid_detection import detect_grid_from_image

logger = logging.getLogger(__name__)

BATCH_SIZE = 50  # Smaller than hash backfill — grid detection is heavier per image


def _sibling_counts(db, image: Image) -> tuple[tuple[int, int], ...]:
    """NxM grid sizes from the file names of other images in the same group."""
    if image.group_id is None:
        return ()
    rows = (
        db.query(Image.grid_width, Image.grid_height)
        .filter(
            Image.group_id == image.group_id,
            Image.id != image.id,
            Image.grid_source == GRID_SOURCE_FILENAME,
            Image.grid_width.isnot(None),
            Image.grid_height.isnot(None),
        )
        .distinct()
        .all()
    )
    counts: dict[tuple[int, int], None] = {}
    for w, h in rows:
        counts[(w, h)] = None
        counts[(h, w)] = None
    return tuple(counts)


def detection_mode(image: Image, force: bool) -> str | None:
    """ "full", "size", or None to leave the image alone."""
    if image.image_type != "battlemap" or image.media_type == "video":
        return None
    if image.grid_source == GRID_SOURCE_USER:
        return None
    if image.grid_source == GRID_SOURCE_FILENAME:
        # A confidence means the size was detected; without one, any size is the file's NxM.
        if image.gridded is not True or (
            image.grid_width is not None and image.grid_confidence is None
        ):
            return None  # explicit "no grid", or an exact NxM
        return "size" if force or image.grid_confidence is None else None
    if image.grid_source == GRID_SOURCE_DETECTOR:
        return "full" if force else None
    return "full"  # no grid information yet


def _memory_estimate(path, width: int, height: int, cfg: PipelineConfig) -> int:
    with PILImage.open(path) as header:
        image_format = header.format
        progressive = bool(header.info.get("progressive") or header.info.get("progression"))
    return grid_detection_bytes(width, height, image_format, progressive, cfg)


def detect_grids_batch(image_ids: list[int], force: bool = False) -> dict:
    """Run grid detection on *image_ids* and update their rows.

    With *force*, re-detect even where grid info exists. Returns detected/skipped/errors counts.
    """
    engine = get_engine(settings.database_url)
    SessionLocal = get_session_local(engine)
    db = SessionLocal()
    image_store = get_image_store()
    cfg = load_pipeline_config()

    detected = skipped = errors = 0
    try:
        images = db.query(Image).filter(Image.id.in_(image_ids)).all()
        for image in images:
            try:
                mode = detection_mode(image, force)
                if mode is None or image.width is None or image.height is None:
                    skipped += 1
                    continue
                file_path = image_store.get_path(image.storage_key)
                if not file_path.exists():
                    logger.warning("Image %s: file not found at %s", image.id, file_path)
                    skipped += 1
                    continue

                size_only = mode == "size"
                reserve = _memory_estimate(file_path, image.width, image.height, cfg)
                with get_memory_budget().reserve(reserve):
                    result = detect_grid_from_image(
                        str(file_path),
                        image.width,
                        image.height,
                        size_only=size_only,
                        pipeline_config=cfg,
                        sibling_counts=_sibling_counts(db, image) if size_only else (),
                    )
                if result["gridded"] is None:  # unreadable; retrying won't help
                    skipped += 1
                    continue
                image.gridded = result["gridded"]
                image.grid_width = result["grid_width"]
                image.grid_height = result["grid_height"]
                image.grid_type = result["grid_type"]
                image.grid_confidence = result["confidence"]
                if not size_only:  # size-only keeps the file name as the source of "gridded"
                    image.grid_source = GRID_SOURCE_DETECTOR
                detected += 1

            except Exception:
                logger.exception("Image %s: grid detection error", image.id)
                errors += 1
        db.commit()
    finally:
        db.close()

    return {"detected": detected, "skipped": skipped, "errors": errors}


def backfill_grid_detection(force: bool = False, progress_fn=None):
    """Detect grid presence/size for battlemaps missing grid info (all battlemaps with *force*)."""
    engine = get_engine(settings.database_url)
    SessionLocal = get_session_local(engine)
    db = SessionLocal()

    try:
        # A superset of what detection_mode() accepts; it makes the final call.
        not_user = or_(Image.grid_source.is_(None), Image.grid_source != GRID_SOURCE_USER)
        query = db.query(Image.id).filter(Image.image_type == "battlemap", not_user)
        if not force:
            # Not yet image-analysed (hex grids have no counts, so grid_width can't be
            # the "not yet processed" signal; the confidence can).
            query = query.filter(
                or_(
                    Image.grid_source.is_(None),
                    and_(Image.gridded.is_(True), Image.grid_confidence.is_(None)),
                )
            )
        image_ids = [row[0] for row in query.order_by(Image.id).all()]
    finally:
        db.close()

    total = len(image_ids)
    mode = "all battlemaps (force)" if force else "battlemaps missing grid info"
    logger.info("Grid backfill: %d %s", total, mode)
    if total == 0:
        return {"total": 0, "detected": 0, "skipped": 0, "errors": 0}

    totals = {"detected": 0, "skipped": 0, "errors": 0}
    for i in range(0, total, BATCH_SIZE):
        result = detect_grids_batch(image_ids[i : i + BATCH_SIZE], force=force)
        for key in totals:
            totals[key] += result[key]
        processed = min(i + BATCH_SIZE, total)
        if progress_fn:
            progress_fn(processed, total, f"Processed {processed}/{total}")

    logger.info(
        "Grid backfill complete: %d detected, %d skipped, %d errors",
        totals["detected"],
        totals["skipped"],
        totals["errors"],
    )
    return {"total": total, **totals}


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(description="Backfill grid detection for battlemaps")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-detect all battlemaps, not just those missing grid info (never user-set grids)",
    )
    args = parser.parse_args()

    backfill_grid_detection(force=args.force)
