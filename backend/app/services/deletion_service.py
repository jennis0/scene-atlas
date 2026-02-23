"""Safe image deletion with ref-counted physical file cleanup."""

import logging
import re

from sqlalchemy.orm import Session

from ..models.database import Image

logger = logging.getLogger(__name__)


def safe_delete_image(db: Session, image: Image) -> None:
    """Delete an image record; only remove physical files if last reference.

    Handles:
    - Ref counting: checks if other Image records share the same storage_key
    - Qdrant cleanup: always deletes the per-image embedding point
    - Thumbnail cleanup: deletes ALL thumbnail sizes, not just medium
    - DB cascade: tags + colors are deleted via cascade

    Args:
        db: Active SQLAlchemy session (caller is responsible for commit)
        image: The Image record to delete
    """
    from . import get_image_store, get_thumbnail_store
    from .qdrant_service import get_qdrant_service

    storage_key = image.storage_key
    thumbnail_key = image.thumbnail_key
    image_id = image.id

    # Count other records sharing this storage_key
    ref_count = (
        db.query(Image).filter(Image.storage_key == storage_key, Image.id != image_id).count()
    )

    # Delete the DB record (cascades tags, colors)
    db.delete(image)
    db.flush()

    # Always delete the per-image Qdrant point
    try:
        get_qdrant_service().delete_image_embedding(image_id)
    except Exception as e:
        logger.warning(f"Failed to delete Qdrant embedding for image {image_id}: {e}")

    # Only delete physical files if this was the last reference
    if ref_count == 0:
        image_store = get_image_store()
        thumbnail_store = get_thumbnail_store()

        try:
            image_store.delete(storage_key)
        except Exception as e:
            logger.warning(f"Failed to delete image file {storage_key}: {e}")

        if thumbnail_key:
            _delete_all_thumbnails(thumbnail_store, thumbnail_key)
    else:
        logger.debug(
            f"Kept physical files for storage_key={storage_key} "
            f"({ref_count} other references remain)"
        )


def _delete_all_thumbnails(thumbnail_store, thumbnail_key: str) -> None:
    """Delete all thumbnail sizes for a given thumbnail key.

    Thumbnail keys follow the pattern: {stem}_{width}x{height}.jpg
    We extract the stem and delete all matching size variants.
    """
    from ..config import settings

    # Extract the stem from the stored key (e.g., "a1b2c3d4_400x400.jpg" -> "a1b2c3d4")
    match = re.match(r"^(.+?)_\d+x\d+\.jpg$", thumbnail_key)
    if not match:
        # Fallback: just delete the one key we have
        try:
            thumbnail_store.delete(thumbnail_key)
        except Exception as e:
            logger.warning(f"Failed to delete thumbnail {thumbnail_key}: {e}")
        return

    stem = match.group(1)
    for width, height in settings.thumbnail_sizes:
        key = f"{stem}_{width}x{height}.jpg"
        try:
            thumbnail_store.delete(key)
        except Exception as e:
            logger.debug(f"Failed to delete thumbnail {key}: {e}")
