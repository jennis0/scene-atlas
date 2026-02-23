"""Backfill content_hash for existing images.

Reads each image file from the ImageStore, computes its SHA-256 digest,
and writes the hash back to the database.

Usage:
    uv run python -m backend.flows.backfill_content_hash
"""

import hashlib
import logging

from backend.app.config import settings
from backend.app.models.database import Image, get_engine, get_session_local
from backend.app.services import get_image_store

logger = logging.getLogger(__name__)

BATCH_SIZE = 100


def _compute_file_hash(file_path) -> str:
    """Compute SHA-256 hex digest of a file, reading in 8KB chunks."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(8192)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def backfill_batch(image_ids: list[int]) -> dict:
    """Compute and store content_hash for a batch of images."""
    engine = get_engine(settings.database_url)
    SessionLocal = get_session_local(engine)
    db = SessionLocal()
    image_store = get_image_store()

    updated = 0
    skipped = 0
    errors = 0

    try:
        images = db.query(Image).filter(Image.id.in_(image_ids)).all()
        for image in images:
            try:
                file_path = image_store.get_path(image.storage_key)
                if not file_path.exists():
                    logger.warning(f"Image {image.id}: file not found at {file_path}")
                    skipped += 1
                    continue

                image.content_hash = _compute_file_hash(file_path)
                updated += 1
            except Exception as e:
                logger.error(f"Image {image.id}: error computing hash: {e}")
                errors += 1

        db.commit()
    finally:
        db.close()

    return {"updated": updated, "skipped": skipped, "errors": errors}


def backfill_content_hash():
    """Backfill SHA-256 content_hash for all images missing one."""
    engine = get_engine(settings.database_url)
    SessionLocal = get_session_local(engine)
    db = SessionLocal()

    try:
        missing = db.query(Image.id).filter(Image.content_hash.is_(None)).all()
        image_ids = [row[0] for row in missing]
    finally:
        db.close()

    total = len(image_ids)
    print(f"Found {total} images without content_hash")

    if total == 0:
        print("Nothing to backfill")
        return {"total": 0, "updated": 0, "skipped": 0, "errors": 0}

    # Process in batches
    totals = {"updated": 0, "skipped": 0, "errors": 0}
    for i in range(0, total, BATCH_SIZE):
        batch_ids = image_ids[i : i + BATCH_SIZE]
        result = backfill_batch(batch_ids)
        totals["updated"] += result["updated"]
        totals["skipped"] += result["skipped"]
        totals["errors"] += result["errors"]
        print(f"  Processed {min(i + BATCH_SIZE, total)}/{total}")

    print(f"Backfill complete: {totals}")
    return {"total": total, **totals}


if __name__ == "__main__":
    backfill_content_hash()
