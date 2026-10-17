"""Backfill content_hash for existing images.

Reads each image file from the ImageStore, computes its SHA-256 digest,
and writes the hash back to the database.

Usage:
    uv run python -m backend.pipeline.backfill_content_hash
"""

import hashlib
import logging

from backend.app.models.database import Image
from backend.app.services import get_image_store
from backend.pipeline.db import pipeline_db

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
    image_store = get_image_store()

    updated = 0
    skipped = 0
    errors = 0

    with pipeline_db() as db:
        images = db.query(Image).filter(Image.id.in_(image_ids)).all()
        for image in images:
            try:
                file_path = image_store.get_path(image.storage_key)
                if not file_path.exists():
                    logger.warning("Image %s: file not found at %s", image.id, file_path)
                    skipped += 1
                    continue

                image.content_hash = _compute_file_hash(file_path)
                updated += 1
            except Exception:
                logger.exception("Image %s: error computing hash", image.id)
                errors += 1

    return {"updated": updated, "skipped": skipped, "errors": errors}


def backfill_content_hash():
    """Backfill SHA-256 content_hash for all images missing one."""
    with pipeline_db() as db:
        missing = db.query(Image.id).filter(Image.content_hash.is_(None)).all()
        image_ids = [row[0] for row in missing]

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
    logging.basicConfig(level=logging.INFO)
    backfill_content_hash()
