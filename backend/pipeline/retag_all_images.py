"""Retag all images using the filename parser.

Removes all auto-assigned tags (source='auto') and reruns the
ImageParser on each image's filename to regenerate tags.
Manually assigned tags (source='manual') are left untouched.

Usage:
    uv run python -m backend.pipeline.retag_all_images
"""

import logging

from backend.app.models.database import Image, Tag, TagCategory
from backend.app.services import ImageParser
from backend.pipeline.db import pipeline_db

logger = logging.getLogger(__name__)

BATCH_SIZE = 200


def _build_parser(db):
    """Create an ImageParser with tag vocabulary loaded from DB."""
    categories = db.query(TagCategory).all()
    cat_dicts = [{"name": c.name, "common_values": c.common_values} for c in categories]
    return ImageParser(tag_categories=cat_dicts)


def retag_batch(image_ids: list[int], parser: ImageParser) -> dict:
    """Delete auto tags for a batch of images and regenerate them atomically.

    The delete + re-tag for each batch is committed in a single transaction so
    that a crash mid-retag only loses tags for the current batch rather than
    the entire library.
    """
    tags_created = 0
    tags_deleted = 0
    errors = 0

    with pipeline_db() as db:
        # Delete auto tags for THIS batch only (atomic with re-tag below)
        tags_deleted = (
            db.query(Tag)
            .filter(Tag.image_id.in_(image_ids), Tag.source == "auto")
            .delete(synchronize_session=False)
        )

        images = db.query(Image).filter(Image.id.in_(image_ids)).all()
        for image in images:
            try:
                # Build set of manually applied (category, value) pairs for this image
                manual_tags = {
                    (t.category, t.value)
                    for t in db.query(Tag)
                    .filter(Tag.image_id == image.id, Tag.source == "manual")
                    .all()
                }
                parsed = parser.parse(image.filename)
                for tag_data in parsed["tags"]:
                    if (tag_data["category"], tag_data["value"]) in manual_tags:
                        continue  # Don't duplicate a manually applied tag
                    db.add(
                        Tag(
                            image_id=image.id,
                            category=tag_data["category"],
                            value=tag_data["value"],
                            confidence=tag_data["confidence"],
                            source="auto",
                        )
                    )
                    tags_created += 1
            except Exception:
                logger.exception("Image %s: error retagging", image.id)
                errors += 1

    return {"tags_created": tags_created, "tags_deleted": tags_deleted, "errors": errors}


def retag_all_images(progress_fn=None):
    """Delete auto tags per batch and regenerate them from filenames.

    Each batch atomically deletes its auto tags and re-creates them in a
    single transaction.  If the process crashes mid-retag, only the current
    batch loses its auto tags — all other batches remain intact.
    """
    with pipeline_db() as db:
        parser = _build_parser(db)

        # Collect all image IDs
        all_ids = [row[0] for row in db.query(Image.id).order_by(Image.id).all()]

    total = len(all_ids)
    print(f"Retagging {total} image(s)...")

    if total == 0:
        print("Nothing to retag")
        return {"total": 0, "tags_created": 0, "tags_deleted": 0, "errors": 0}

    # Process in batches — each batch atomically deletes + re-creates auto tags
    totals = {"tags_created": 0, "tags_deleted": 0, "errors": 0}
    for i in range(0, total, BATCH_SIZE):
        batch_ids = all_ids[i : i + BATCH_SIZE]
        result = retag_batch(batch_ids, parser)
        totals["tags_created"] += result["tags_created"]
        totals["tags_deleted"] += result["tags_deleted"]
        totals["errors"] += result["errors"]
        processed = min(i + BATCH_SIZE, total)
        print(f"  Processed {processed}/{total}")
        if progress_fn:
            progress_fn(processed, total, f"Processed {processed}/{total}")

    print(
        f"Done. Deleted {totals['tags_deleted']} and created {totals['tags_created']} "
        f"auto tag(s) across {total} image(s)."
    )
    return {"total": total, **totals}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    retag_all_images()
