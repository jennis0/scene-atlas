"""Services package."""

from .deletion_service import safe_delete_image
from .image_parser import ImageParser
from .image_store import ImageStore
from .qdrant_service import QdrantService, get_qdrant_service

# Lazy-initialized image stores (initialized after settings are loaded)
_image_store = None
_thumbnail_store = None


def get_image_store() -> ImageStore:
    """Get the image store instance (hash-sharded object store)."""
    global _image_store
    if _image_store is None:
        from ..config import settings

        _image_store = ImageStore(settings.store_images_dir)
    return _image_store


def get_thumbnail_store() -> ImageStore:
    """Get the thumbnail store instance (hash-sharded object store)."""
    global _thumbnail_store
    if _thumbnail_store is None:
        from ..config import settings

        _thumbnail_store = ImageStore(settings.store_thumbnails_dir)
    return _thumbnail_store


def get_clip_service():
    """Get or create the CLIP service singleton.

    Imported lazily to avoid triggering the transformers library's
    module-directory scan at import time, which causes an OSError on Windows.
    """
    from .clip_service import get_clip_service as _get

    return _get()


__all__ = [
    "ImageParser",
    "get_clip_service",
    "ImageStore",
    "get_image_store",
    "get_thumbnail_store",
    "QdrantService",
    "get_qdrant_service",
    "safe_delete_image",
]
