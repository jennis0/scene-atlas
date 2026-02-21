"""Services package."""

from .battlemap_parser import BattlemapParser
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


def get_clip_service():
    """Get or create the CLIP service singleton.

    Imported lazily so that loading this package (which happens on every
    Prefect flow-run startup) does not trigger the transformers library's
    module-directory scan, which causes an OSError on Windows.
    """
    from .clip_service import get_clip_service as _get
    return _get()


__all__ = [
    "BattlemapParser",
    "get_clip_service",
    "ImageStore",
    "get_image_store",
    "get_thumbnail_store",
    "QdrantService",
    "qdrant_service",
]
