"""System information endpoint — storage usage, library stats, data directory."""

import logging
import os
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..config import settings
from ..models.database import Image, ImageGroup, get_db

logger = logging.getLogger(__name__)
router = APIRouter()


def _dir_size(path: Path) -> int:
    """Recursively sum file sizes under *path*; returns 0 if path doesn't exist."""
    total = 0
    try:
        for entry in os.scandir(path):
            if entry.is_file(follow_symlinks=False):
                total += entry.stat().st_size
            elif entry.is_dir(follow_symlinks=False):
                total += _dir_size(Path(entry.path))
    except (PermissionError, OSError):
        pass
    return total


@router.get("/info")
def system_info(db: Session = Depends(get_db)):
    """Return storage usage and library statistics.

    Intended for the desktop settings panel (app mode).  Also available in
    server mode for diagnostics.
    """
    image_count = db.query(Image).count()
    group_count = db.query(ImageGroup).count()

    images_bytes     = _dir_size(settings.store_images_dir)
    thumbnails_bytes = _dir_size(settings.store_thumbnails_dir)
    qdrant_bytes     = _dir_size(settings.qdrant_path)

    return {
        "storage_path": str(settings.data_dir),
        "mode": settings.app_mode,
        "storage": {
            "images_bytes":     images_bytes,
            "thumbnails_bytes": thumbnails_bytes,
            "qdrant_bytes":     qdrant_bytes,
            "total_bytes":      images_bytes + thumbnails_bytes + qdrant_bytes,
        },
        "library": {
            "image_count": image_count,
            "group_count": group_count,
        },
    }
