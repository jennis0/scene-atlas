"""Services package."""

from .battlemap_parser import BattlemapParser
from .clip_service import CLIPService, get_clip_service
from .image_store import ImageStore
from .qdrant_service import QdrantService, qdrant_service

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


__all__ = [
    "BattlemapParser",
    "CLIPService",
    "get_clip_service",
    "ImageStore",
    "get_image_store",
    "get_thumbnail_store",
    "QdrantService",
    "qdrant_service",
]
