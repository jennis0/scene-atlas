"""Image processing tasks for Prefect flows."""

import logging
from pathlib import Path
from typing import Tuple

from PIL import Image
from prefect import task

from backend.app.config import settings
from backend.app.services import get_thumbnail_store

logger = logging.getLogger(__name__)


@task(name="generate_thumbnails", retries=2)
def generate_thumbnails(image_path: Path, storage_key_stem: str) -> dict[str, str]:
    """Generate thumbnails at different sizes and store via ImageStore.

    Args:
        image_path: Path to the original image file
        storage_key_stem: UUID stem for naming thumbnails (e.g., "a1b2c3d4e5f6")

    Returns:
        Dict mapping size names to thumbnail storage keys
    """
    try:
        image = Image.open(image_path)
        image = image.convert("RGB")  # Ensure RGB mode

        thumbnail_store = get_thumbnail_store()
        thumbnail_keys = {}

        for idx, (width, height) in enumerate(settings.thumbnail_sizes):
            # Create thumbnail
            thumb = image.copy()
            thumb.thumbnail((width, height), Image.Resampling.LANCZOS)

            # Generate storage key for this thumbnail
            thumb_key = f"{storage_key_stem}_{width}x{height}.jpg"

            # Save to a temp file, then put into store
            thumb_path = thumbnail_store.get_path(thumb_key)
            thumb_path.parent.mkdir(parents=True, exist_ok=True)
            thumb.save(thumb_path, quality=85, optimize=True)

            size_name = ["small", "medium", "large"][idx] if idx < 3 else f"size_{idx}"
            thumbnail_keys[size_name] = thumb_key

            logger.debug(f"Generated {size_name} thumbnail: {thumb_key}")

        return thumbnail_keys

    except Exception as e:
        logger.error(f"Error generating thumbnails for {image_path}: {e}")
        raise


@task(name="get_image_dimensions", retries=2)
def get_image_dimensions(image_path: Path) -> Tuple[int, int]:
    """Get image width and height.

    Args:
        image_path: Path to the image

    Returns:
        Tuple of (width, height)
    """
    try:
        with Image.open(image_path) as img:
            return img.size
    except Exception as e:
        logger.error(f"Error getting dimensions for {image_path}: {e}")
        raise


@task(name="get_file_size", retries=2)
def get_file_size(image_path: Path) -> int:
    """Get file size in bytes.

    Args:
        image_path: Path to the file

    Returns:
        File size in bytes
    """
    try:
        return image_path.stat().st_size
    except Exception as e:
        logger.error(f"Error getting file size for {image_path}: {e}")
        raise
