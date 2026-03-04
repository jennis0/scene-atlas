"""Safe image deletion with ref-counted physical file cleanup."""

import logging
import re

from sqlalchemy.orm import Session

from ..models.database import Image, ImageGroup, ImportGroupJob

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

    # Delete the DB record (cascades tags, colors)
    db.delete(image)
    db.flush()

    # Count remaining references *after* this record is removed from the session,
    # closing the race window that existed when counting before deletion.
    ref_count = db.query(Image).filter(Image.storage_key == storage_key).count()

    # Always delete the per-image Qdrant point
    try:
        get_qdrant_service().delete_image_embedding(image_id)
    except Exception as e:
        logger.warning("Failed to delete Qdrant embedding for image %s: %s", image_id, e)

    # Only delete physical files if this was the last reference
    if ref_count == 0:
        image_store = get_image_store()
        thumbnail_store = get_thumbnail_store()

        try:
            image_store.delete(storage_key)
        except Exception as e:
            logger.warning("Failed to delete image file %s: %s", storage_key, e)

        if thumbnail_key:
            _delete_all_thumbnails(thumbnail_store, thumbnail_key)
    else:
        logger.debug(
            "Kept physical files for storage_key=%s (%s other references remain)",
            storage_key,
            ref_count,
        )


def cleanup_import_images(job_id: str, db: Session) -> int:
    """Delete all Image rows (and their files/embeddings) attached to an import job.

    Implements ref-counted physical file deletion: only removes files when no
    other Image rows share the same storage_key. Also cleans up now-empty
    ImageGroups that were created by this import.

    Does NOT commit — caller is responsible.
    Returns the count of Image rows deleted.
    """
    from . import get_image_store, get_thumbnail_store
    from .qdrant_service import get_qdrant_service

    images = db.query(Image).filter(Image.import_job_id == job_id).all()
    if not images:
        return 0

    image_store = get_image_store()
    thumbnail_store = get_thumbnail_store()
    qdrant = get_qdrant_service()
    deleted_count = 0
    image_ids_to_delete = []
    group_ids_to_check: set[int] = set()

    for image in images:
        image_ids_to_delete.append(image.id)
        if image.group_id:
            group_ids_to_check.add(image.group_id)

        sibling_count = (
            db.query(Image)
            .filter(Image.storage_key == image.storage_key, Image.id != image.id)
            .count()
        )
        if sibling_count == 0:
            if image.storage_key:
                image_store.delete(image.storage_key)
            if image.thumbnail_key:
                thumbnail_store.delete(image.thumbnail_key)

        db.delete(image)
        deleted_count += 1

    if image_ids_to_delete:
        try:
            qdrant.delete_embeddings(image_ids_to_delete)
        except Exception:
            logger.warning("Qdrant cleanup failed for job %s (non-fatal)", job_id, exc_info=True)

    db.flush()

    # Clean up now-empty ImageGroups that were created by this import
    group_job_rows = (
        db.query(ImportGroupJob.created_group_id)
        .filter(ImportGroupJob.job_id == job_id, ImportGroupJob.created_group_id.isnot(None))
        .all()
    )
    created_group_ids = {row[0] for row in group_job_rows}
    for group_id in created_group_ids & group_ids_to_check:
        remaining = db.query(Image).filter(Image.group_id == group_id).count()
        if remaining == 0:
            grp = db.query(ImageGroup).filter(ImageGroup.id == group_id).first()
            if grp:
                db.delete(grp)

    return deleted_count


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
            logger.warning("Failed to delete thumbnail %s: %s", thumbnail_key, e)
        return

    stem = match.group(1)
    for width, height in settings.thumbnail_sizes:
        key = f"{stem}_{width}x{height}.jpg"
        try:
            thumbnail_store.delete(key)
        except Exception as e:
            logger.debug("Failed to delete thumbnail %s: %s", key, e)
