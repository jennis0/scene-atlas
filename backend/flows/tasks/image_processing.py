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
def generate_thumbnails(image_path: str, storage_key_stem: str) -> dict:
    """Generate thumbnails at different sizes and store via ImageStore.

    Also returns original image dimensions to avoid a separate PIL open.

    Args:
        image_path: Path to the original image file (as string for serialization)
        storage_key_stem: UUID stem for naming thumbnails (e.g., "a1b2c3d4e5f6")

    Returns:
        Dict with 'keys' (size name -> storage key) and 'dimensions' (width, height)
    """
    try:
        image_path = Path(image_path)
        image = Image.open(image_path)
        image = image.convert("RGB")  # Ensure RGB mode
        dimensions = image.size  # (width, height) - capture before thumbnailing

        thumbnail_store = get_thumbnail_store()
        thumbnail_keys = {}

        for idx, (width, height) in enumerate(settings.thumbnail_sizes):
            # Create thumbnail - use LANCZOS for large, BILINEAR for small/medium
            thumb = image.copy()
            resampling = Image.Resampling.LANCZOS if idx == len(settings.thumbnail_sizes) - 1 else Image.Resampling.BILINEAR
            thumb.thumbnail((width, height), resampling)

            # Generate storage key for this thumbnail
            thumb_key = f"{storage_key_stem}_{width}x{height}.jpg"

            # Save to a temp file, then put into store
            thumb_path = thumbnail_store.get_path(thumb_key)
            thumb_path.parent.mkdir(parents=True, exist_ok=True)
            thumb.save(thumb_path, quality=85, optimize=True)

            size_name = ["small", "medium", "large"][idx] if idx < 3 else f"size_{idx}"
            thumbnail_keys[size_name] = thumb_key

            logger.debug(f"Generated {size_name} thumbnail: {thumb_key}")

        return {"keys": thumbnail_keys, "dimensions": dimensions}

    except Exception as e:
        logger.error(f"Error generating thumbnails for {image_path}: {e}")
        raise


@task(name="generate_preview_thumbnail", retries=1)
def generate_preview_thumbnail(
    image_path: str,
    staging_dir: str,
    relative_path: str,
    size: int = 120,
) -> str | None:
    """Generate a small preview thumbnail for the import preview UI.

    Saves the thumbnail into a .thumbs/ subdirectory of the staging dir.
    The filename is derived from the relative path with slashes replaced.

    Args:
        image_path: Absolute path to the source image
        staging_dir: Path to the staging directory (data/staging/{job_id})
        relative_path: Relative path of the file within staging
        size: Thumbnail size (square, default 120px)

    Returns:
        The safe filename of the generated thumbnail, or None on failure
    """
    try:
        thumbs_dir = Path(staging_dir) / ".thumbs"
        thumbs_dir.mkdir(parents=True, exist_ok=True)

        # Convert relative path to safe filename: replace slashes and backslashes
        safe_name = relative_path.replace("/", "__").replace("\\", "__")
        safe_name = Path(safe_name).stem + ".jpg"

        thumb_path = thumbs_dir / safe_name

        image = Image.open(Path(image_path))
        image = image.convert("RGB")
        image.thumbnail((size, size), Image.Resampling.BILINEAR)
        image.save(thumb_path, format="JPEG", quality=70, optimize=True)

        logger.debug(f"Generated preview thumbnail: {safe_name}")
        return safe_name

    except Exception as e:
        logger.warning(f"Failed to generate preview thumbnail for {relative_path}: {e}")
        return None


@task(name="get_image_dimensions", retries=2)
def get_image_dimensions(image_path: str) -> Tuple[int, int]:
    """Get image width and height.

    Args:
        image_path: Path to the image (as string for serialization)

    Returns:
        Tuple of (width, height)
    """
    try:
        with Image.open(Path(image_path)) as img:
            return img.size
    except Exception as e:
        logger.error(f"Error getting dimensions for {image_path}: {e}")
        raise


@task(name="get_file_size", retries=2)
def get_file_size(image_path: str) -> int:
    """Get file size in bytes.

    Args:
        image_path: Path to the file (as string for serialization)

    Returns:
        File size in bytes
    """
    try:
        return Path(image_path).stat().st_size
    except Exception as e:
        logger.error(f"Error getting file size for {image_path}: {e}")
        raise
