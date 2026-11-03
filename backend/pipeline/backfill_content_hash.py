"""Backfill content_hash and stored_hash for existing images.

Reads each image file from the ImageStore, computes its SHA-256 digest,
and writes the hash back to the database.

``backfill_stored_hash`` runs at startup when any image lacks a ``stored_hash`` (rows from
before it existed): exports name the stored file by it (design/export-backup-move.md §2).

Usage:
    uv run python -m backend.pipeline.backfill_content_hash
"""

import hashlib
import logging

from sqlalchemy.orm import selectinload

from backend.app.file_hash import file_sha256
from backend.app.models.database import Image
from backend.app.services.originals import OriginalUnavailable, original_path
from backend.app.services.shutdown import raise_if_shutting_down
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
    updated = 0
    skipped = 0
    errors = 0

    with pipeline_db() as db:
        images = (
            db.query(Image)
            .options(selectinload(Image.source_file))
            .filter(Image.id.in_(image_ids))
            .all()
        )
        for image in images:
            try:
                try:
                    file_path = original_path(image)
                except OriginalUnavailable as exc:
                    logger.warning("Image %s: %s", image.id, exc.reason)
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
        raise_if_shutting_down()
        batch_ids = image_ids[i : i + BATCH_SIZE]
        result = backfill_batch(batch_ids)
        totals["updated"] += result["updated"]
        totals["skipped"] += result["skipped"]
        totals["errors"] += result["errors"]
        print(f"  Processed {min(i + BATCH_SIZE, total)}/{total}")

    print(f"Backfill complete: {totals}")
    return {"total": total, **totals}


STORED_HASH_JOB = "Computing file hashes"


def images_missing_stored_hash(db) -> int:
    return db.query(Image.id).filter(Image.stored_hash.is_(None)).count()


def backfill_stored_hash(progress_fn=None) -> dict:
    """Hash the file each image reads from (the stored file, or the linked file) where
    ``stored_hash`` is NULL; set ``content_hash`` too where that is NULL, since then the
    file is all there is to go by. Images whose file is missing are left for a later run."""
    with pipeline_db() as db:
        image_ids = [i for (i,) in db.query(Image.id).filter(Image.stored_hash.is_(None))]
    totals = {"total": len(image_ids), "updated": 0, "skipped": 0}
    for start in range(0, len(image_ids), BATCH_SIZE):
        raise_if_shutting_down()
        with pipeline_db() as db:
            batch = (
                db.query(Image)
                .options(selectinload(Image.source_file))
                .filter(Image.id.in_(image_ids[start : start + BATCH_SIZE]))
                .all()
            )
            for image in batch:
                try:
                    digest = file_sha256(original_path(image))
                except (OriginalUnavailable, OSError) as exc:
                    logger.warning("Image %s: can't hash its file: %s", image.id, exc)
                    totals["skipped"] += 1
                    continue
                image.stored_hash = digest
                if image.content_hash is None:
                    image.content_hash = digest
                totals["updated"] += 1
        if progress_fn:
            done = min(start + BATCH_SIZE, len(image_ids))
            progress_fn(done, len(image_ids), f"Hashed {done:,} of {len(image_ids):,} files")
    logger.info("Stored-hash backfill: %s", totals)
    return totals


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    backfill_content_hash()
