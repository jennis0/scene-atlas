"""Retag all images using the filename parser.

Removes all auto-assigned tags (source='auto') and reruns the
ImageParser on each image's filename to regenerate tags.
Manually assigned tags (source='manual') are left untouched.

Usage:
    uv run python -m backend.flows.retag_all_images
"""

import logging
import os

from prefect import flow, task

os.environ.setdefault("PREFECT_API_URL", "http://localhost:4200/api")

from backend.app.config import settings
from backend.app.models.database import (
    Image,
    Tag,
    TagCategory,
    get_engine,
    get_session_local,
)
from backend.app.services import ImageParser

logger = logging.getLogger(__name__)

BATCH_SIZE = 200


def _build_parser(db):
    """Create an ImageParser with tag vocabulary loaded from DB."""
    categories = db.query(TagCategory).all()
    cat_dicts = [{"name": c.name, "common_values": c.common_values} for c in categories]
    return ImageParser(tag_categories=cat_dicts)


@task(name="retag_batch")
def retag_batch(image_ids: list[int], parser: ImageParser) -> dict:
    """Retag a batch of images."""
    engine = get_engine(settings.database_url)
    SessionLocal = get_session_local(engine)
    db = SessionLocal()

    tags_created = 0
    errors = 0

    try:
        images = db.query(Image).filter(Image.id.in_(image_ids)).all()
        for image in images:
            try:
                parsed = parser.parse(image.filename)
                for tag_data in parsed["tags"]:
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
            except Exception as e:
                logger.error(f"Image {image.id}: error retagging: {e}")
                errors += 1

        db.commit()
    finally:
        db.close()

    return {"tags_created": tags_created, "errors": errors}


@flow(name="retag_all_images", log_prints=True)
def retag_all_images():
    """Delete all auto tags and regenerate them from filenames."""
    engine = get_engine(settings.database_url)
    SessionLocal = get_session_local(engine)
    db = SessionLocal()

    try:
        parser = _build_parser(db)

        # Delete all auto tags in one go
        deleted = db.query(Tag).filter(Tag.source == "auto").delete()
        db.commit()
        print(f"Deleted {deleted} auto-assigned tag(s).")

        # Collect all image IDs
        all_ids = [row[0] for row in db.query(Image.id).order_by(Image.id).all()]
    finally:
        db.close()

    total = len(all_ids)
    print(f"Retagging {total} image(s)...")

    if total == 0:
        print("Nothing to retag")
        return {"total": 0, "tags_created": 0, "errors": 0}

    # Process in batches
    totals = {"tags_created": 0, "errors": 0}
    for i in range(0, total, BATCH_SIZE):
        batch_ids = all_ids[i : i + BATCH_SIZE]
        result = retag_batch(batch_ids, parser)
        totals["tags_created"] += result["tags_created"]
        totals["errors"] += result["errors"]
        print(f"  Processed {min(i + BATCH_SIZE, total)}/{total}")

    print(
        f"Done. Created {totals['tags_created']} new auto tag(s) "
        f"across {total} image(s)."
    )
    return {"total": total, **totals}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    retag_all_images()
