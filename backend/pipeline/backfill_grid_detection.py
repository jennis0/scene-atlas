"""Backfill image-based grid detection for existing battlemap images.

Runs the GridDetector on battlemaps that are missing grid information,
updating gridded, grid_width, grid_height, grid_type, and grid_confidence.

Targets three categories of images:
1. gridded=None (no filename hint) → detect presence + size
2. gridded=True but grid_width=None (filename says gridded, no dimensions) → detect size only
3. Optionally re-detect all battlemaps (--force flag)

Usage:
    uv run python -m backend.pipeline.backfill_grid_detection
"""

import logging

from sqlalchemy import and_, or_

from backend.app.config import settings
from backend.app.models.database import Image, get_engine, get_session_local
from backend.app.services import get_image_store
from backend.app.services.grid_detector import GridDetector

logger = logging.getLogger(__name__)

BATCH_SIZE = 50  # Smaller than hash backfill — grid detection is heavier per image


def _build_detector() -> GridDetector:
    """Create a GridDetector using DB-backed AppSettings."""
    from backend.app.services.app_settings import get_settings as get_app_settings

    engine = get_engine(settings.database_url)
    SessionLocal = get_session_local(engine)
    db = SessionLocal()
    try:
        app_settings = get_app_settings(db)
        return GridDetector(
            min_cell_px=app_settings.grid_min_cell_px,
            max_cell_px=app_settings.grid_max_cell_px,
            max_dim=app_settings.grid_detection_max_dim,
            presence_threshold=app_settings.grid_presence_threshold,
            size_threshold=app_settings.grid_size_threshold,
            period_ratio_threshold=app_settings.grid_period_ratio_threshold,
            hex_rot_conf=app_settings.grid_hex_rot_conf,
        )
    finally:
        db.close()


def detect_grids_batch(image_ids: list[int], force: bool = False) -> dict:
    """Run grid detection on *image_ids* and update their rows.

    With *force*, re-detect even where grid info exists. Returns detected/skipped/errors counts.
    """
    engine = get_engine(settings.database_url)
    SessionLocal = get_session_local(engine)
    db = SessionLocal()
    image_store = get_image_store()

    detector = _build_detector()

    detected = 0
    skipped = 0
    errors = 0

    try:
        images = db.query(Image).filter(Image.id.in_(image_ids)).all()
        for image in images:
            try:
                # Skip non-battlemaps and videos
                if image.image_type != "battlemap" or image.media_type == "video":
                    logger.debug(
                        "Image %s: skipped (type=%s, media=%s)",
                        image.id,
                        image.image_type,
                        image.media_type,
                    )
                    skipped += 1
                    continue

                # Skip if filename explicitly says no grid
                if image.gridded is False and not force:
                    logger.debug("Image %s: skipped (gridded=False from filename)", image.id)
                    skipped += 1
                    continue

                # Resolve file path from store
                file_path = image_store.get_path(image.storage_key)
                if not file_path.exists():
                    logger.warning("Image %s: file not found at %s", image.id, file_path)
                    skipped += 1
                    continue

                if image.width is None or image.height is None:
                    logger.warning("Image %s: missing dimensions, skipping", image.id)
                    skipped += 1
                    continue

                # Decide detection mode
                if image.gridded is True and image.grid_width is None:
                    # Filename says gridded but no dimensions — size only
                    result = detector.detect_size_only(file_path, image.width, image.height)
                else:
                    # Full detection (presence + size)
                    result = detector.detect(file_path, image.width, image.height)

                # Always write results to prevent re-querying.
                # Detector returns gridded=None only when the file is
                # unreadable; treat that as False for DB purposes since
                # retrying won't help.
                result_gridded = result["gridded"] if result["gridded"] is not None else False
                if image.gridded is None or result_gridded is True:
                    image.gridded = result_gridded
                if result["grid_width"] is not None:
                    image.grid_width = result["grid_width"]
                    image.grid_height = result["grid_height"]
                image.grid_type = result["grid_type"]
                image.grid_confidence = result["confidence"]
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
        if force:
            # All battlemaps
            query = db.query(Image.id).filter(Image.image_type == "battlemap").order_by(Image.id)
        else:
            # Only battlemaps that haven't been image-analysed yet:
            # - gridded is None (no filename hint, never detected)
            # - gridded is True but grid_confidence is None (filename says gridded,
            #   but image analysis never ran — e.g. hex grids have grid_width=None
            #   by design, so we can't use grid_width as the "not yet processed" signal)
            # Exclude gridded=False (filename explicitly said no grid)
            query = (
                db.query(Image.id)
                .filter(
                    Image.image_type == "battlemap",
                    or_(
                        Image.gridded.is_(None),
                        and_(
                            Image.gridded.is_(True),
                            Image.grid_confidence.is_(None),
                        ),
                    ),
                )
                .order_by(Image.id)
            )

        image_ids = [row[0] for row in query.all()]
    finally:
        db.close()

    total = len(image_ids)
    mode = "all battlemaps (force)" if force else "battlemaps missing grid info"
    print(f"Found {total} {mode}")

    if total == 0:
        print("Nothing to process")
        return {"total": 0, "detected": 0, "skipped": 0, "errors": 0}

    # Process in batches
    totals = {"detected": 0, "skipped": 0, "errors": 0}
    for i in range(0, total, BATCH_SIZE):
        batch_ids = image_ids[i : i + BATCH_SIZE]
        result = detect_grids_batch(batch_ids, force=force)
        totals["detected"] += result["detected"]
        totals["skipped"] += result["skipped"]
        totals["errors"] += result["errors"]
        processed = min(i + BATCH_SIZE, total)
        print(f"  Processed {processed}/{total}")
        if progress_fn:
            progress_fn(processed, total, f"Processed {processed}/{total}")

    print(
        f"Grid detection complete: {totals['detected']} detected, "
        f"{totals['skipped']} skipped, {totals['errors']} errors"
    )
    return {"total": total, **totals}


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(description="Backfill grid detection for battlemaps")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-detect all battlemaps, not just those missing grid info",
    )
    args = parser.parse_args()

    backfill_grid_detection(force=args.force)
