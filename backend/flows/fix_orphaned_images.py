"""Fix orphaned images that have no group.

Finds all images with group_id = NULL and assigns them all
to a single "Uncategorised" group.

Usage:
    uv run python -m backend.flows.fix_orphaned_images
"""

import logging

from backend.app.config import settings
from backend.app.models.database import (
    Image,
    ImageGroup,
    get_engine,
    get_session_local,
)

logger = logging.getLogger(__name__)

UNCATEGORISED_NAME = "Uncategorised"


def fix_orphaned_images():
    """Add all ungrouped images to a single 'Uncategorised' group."""
    engine = get_engine(settings.database_url)
    SessionLocal = get_session_local(engine)
    db = SessionLocal()

    try:
        orphans = db.query(Image).filter(Image.group_id.is_(None)).all()

        if not orphans:
            print("No orphaned images found.")
            return

        print(f"Found {len(orphans)} orphaned image(s).")

        # Reuse existing Uncategorised group if one exists
        grp = db.query(ImageGroup).filter(ImageGroup.base_name == UNCATEGORISED_NAME).first()
        if grp:
            print(f"Using existing '{UNCATEGORISED_NAME}' group (id={grp.id}).")
        else:
            grp = ImageGroup(
                base_name=UNCATEGORISED_NAME,
                primary_image_id=orphans[0].id,
            )
            db.add(grp)
            db.flush()
            print(f"Created '{UNCATEGORISED_NAME}' group (id={grp.id}).")

        for img in orphans:
            img.group_id = grp.id

        db.commit()
        print(f"Done. Assigned {len(orphans)} image(s) to '{UNCATEGORISED_NAME}'.")

    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    fix_orphaned_images()
