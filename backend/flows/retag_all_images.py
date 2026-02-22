"""Retag all images using the filename parser.

Removes all auto-assigned tags (source='auto') and reruns the
BattlemapParser on each image's filename to regenerate tags.
Manually assigned tags (source='manual') are left untouched.

Usage:
    uv run python -m backend.flows.retag_all_images
"""

import logging

from backend.app.config import settings
from backend.app.models.database import (
    Image,
    Tag,
    TagCategory,
    get_engine,
    get_session_local,
)
from backend.app.services import BattlemapParser

logger = logging.getLogger(__name__)

BATCH_SIZE = 200


def _build_parser(db):
    """Create a BattlemapParser with tag vocabulary loaded from DB."""
    categories = db.query(TagCategory).all()
    cat_dicts = [{"name": c.name, "common_values": c.common_values} for c in categories]
    return BattlemapParser(tag_categories=cat_dicts)


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

        # Process images in batches
        total_images = db.query(Image).count()
        print(f"Retagging {total_images} image(s)...")

        total_tags = 0
        offset = 0

        while offset < total_images:
            images = db.query(Image).order_by(Image.id).offset(offset).limit(BATCH_SIZE).all()
            if not images:
                break

            for image in images:
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
                    total_tags += 1

            db.commit()
            offset += BATCH_SIZE
            print(f"  Processed {min(offset, total_images)}/{total_images} images...")

        print(f"Done. Created {total_tags} new auto tag(s) across {total_images} image(s).")

    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    retag_all_images()
