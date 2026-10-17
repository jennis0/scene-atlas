"""Safe image deletion with ref-counted physical file cleanup."""

import logging
import re
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from ..models.database import Image

logger = logging.getLogger(__name__)


def safe_delete_image(db: Session, image: Image) -> None:
    """Delete an image row; remove its files only if no other row shares them.

    Always deletes the image's embedding and all thumbnail sizes; tags and
    colors go via cascade. The caller commits.
    """
    from . import get_image_store, get_thumbnail_store
    from .lancedb_service import get_lancedb_service

    storage_key = image.storage_key
    thumbnail_key = image.thumbnail_key
    image_id = image.id

    # Delete the DB record (cascades tags, colors)
    db.delete(image)
    db.flush()

    # Count remaining references *after* this record is removed from the session,
    # closing the race window that existed when counting before deletion.
    ref_count = db.query(Image).filter(Image.storage_key == storage_key).count()

    # Always delete the per-image LanceDB point
    try:
        get_lancedb_service().delete_image_embedding(image_id)
    except Exception as e:
        logger.warning("Failed to delete LanceDB embedding for image %s: %s", image_id, e)

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


@dataclass
class PendingFileDeletes:
    """Files and vectors to remove once the row deletions have committed.

    Deleting files only after the commit means a failed commit can never leave
    rows pointing at missing files; at worst an orphaned file is left for the
    orphan sweep.
    """

    storage_keys: list[str] = field(default_factory=list)
    thumbnail_keys: list[str] = field(default_factory=list)
    image_ids: list[int] = field(default_factory=list)

    def apply(self) -> None:
        from . import get_image_store, get_thumbnail_store
        from .lancedb_service import get_lancedb_service

        image_store = get_image_store()
        thumbnail_store = get_thumbnail_store()
        for key in self.storage_keys:
            try:
                image_store.delete(key)
            except Exception as e:
                logger.warning("Failed to delete image file %s: %s", key, e)
        for key in self.thumbnail_keys:
            _delete_all_thumbnails(thumbnail_store, key)
        svc = get_lancedb_service()
        for start in range(0, len(self.image_ids), _CHUNK):
            try:
                svc.delete_embeddings(self.image_ids[start : start + _CHUNK])
            except Exception:
                logger.warning("LanceDB cleanup failed (non-fatal)", exc_info=True)


_CHUNK = 500


def delete_image_rows(db: Session, images: list[Image]) -> PendingFileDeletes:
    """Delete image rows (tags/colours cascade) and return the files to remove after commit.

    Stored files still referenced by another image (legacy shared-storage
    records) are kept. Does NOT commit.
    """
    pending = PendingFileDeletes()
    if not images:
        return pending
    candidates = {img.storage_key: img.thumbnail_key for img in images if img.storage_key}
    pending.image_ids = [img.id for img in images]
    for image in images:
        db.delete(image)
    db.flush()

    keys = sorted(candidates)
    still_used: set[str] = set()
    for start in range(0, len(keys), _CHUNK):
        chunk = keys[start : start + _CHUNK]
        still_used |= {
            key for (key,) in db.query(Image.storage_key).filter(Image.storage_key.in_(chunk))
        }
    for key in keys:
        if key not in still_used:
            pending.storage_keys.append(key)
            if thumb := candidates[key]:
                pending.thumbnail_keys.append(thumb)
    return pending


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
