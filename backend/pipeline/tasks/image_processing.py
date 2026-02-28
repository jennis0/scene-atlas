"""Image processing tasks."""

from pathlib import Path

from PIL import Image

from backend.app.config import settings
from backend.app.services import get_thumbnail_store
from backend.pipeline.logger import get_logger


def generate_thumbnails(image_path: str, storage_key_stem: str) -> dict:
    """Generate thumbnails at different sizes and store via ImageStore.

    Also returns original image dimensions to avoid a separate PIL open.

    Args:
        image_path: Path to the original image file (as string for serialization)
        storage_key_stem: UUID stem for naming thumbnails (e.g., "a1b2c3d4e5f6")

    Returns:
        Dict with 'keys' (size name -> storage key) and 'dimensions' (width, height)
    """
    logger = get_logger(__name__)
    try:
        image_path = Path(image_path)
        thumbnail_store = get_thumbnail_store()
        thumbnail_keys = {}

        with Image.open(image_path) as orig:
            with orig.convert("RGB") as image:
                dimensions = image.size  # (width, height) - capture before thumbnailing

                for idx, (width, height) in enumerate(settings.thumbnail_sizes):
                    # Generate storage key for this thumbnail
                    thumb_key = f"{storage_key_stem}_{width}x{height}.jpg"

                    # Save to a temp file, then put into store
                    thumb_path = thumbnail_store.get_path(thumb_key)
                    thumb_path.parent.mkdir(parents=True, exist_ok=True)

                    # Copy, resize, save, then immediately close to free memory
                    thumb = image.copy()
                    thumb.thumbnail((width, height), Image.Resampling.LANCZOS)
                    thumb.save(thumb_path, quality=85, optimize=True)
                    thumb.close()

                    size_name = ["small", "medium", "large"][idx] if idx < 3 else f"size_{idx}"
                    thumbnail_keys[size_name] = thumb_key

                    logger.debug("Generated %s thumbnail: %s", size_name, thumb_key)

        return {"keys": thumbnail_keys, "dimensions": dimensions}

    except Exception as e:
        logger.error("Error generating thumbnails for %s: %s", image_path, e)
        raise


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
    logger = get_logger(__name__)
    try:
        thumbs_dir = Path(staging_dir) / ".thumbs"
        thumbs_dir.mkdir(parents=True, exist_ok=True)

        # Convert relative path to safe filename: replace slashes and backslashes
        safe_name = relative_path.replace("/", "__").replace("\\", "__")
        safe_name = Path(safe_name).stem + ".jpg"

        thumb_path = thumbs_dir / safe_name

        image = Image.open(Path(image_path))
        image = image.convert("RGB")
        image.thumbnail((size, size), Image.Resampling.LANCZOS)
        image.save(thumb_path, format="JPEG", quality=85, optimize=True)

        logger.debug("Generated preview thumbnail: %s", safe_name)
        return safe_name

    except Exception as e:
        logger.warning("Failed to generate preview thumbnail for %s: %s", relative_path, e)
        return None


def get_image_dimensions(image_path: str) -> tuple[int, int]:
    """Get image width and height.

    Args:
        image_path: Path to the image (as string for serialization)

    Returns:
        Tuple of (width, height)
    """
    logger = get_logger(__name__)
    try:
        with Image.open(Path(image_path)) as img:
            return img.size
    except Exception as e:
        logger.error("Error getting dimensions for %s: %s", image_path, e)
        raise


def get_file_size(image_path: str) -> int:
    """Get file size in bytes.

    Args:
        image_path: Path to the file (as string for serialization)

    Returns:
        File size in bytes
    """
    logger = get_logger(__name__)
    try:
        return Path(image_path).stat().st_size
    except Exception as e:
        logger.error("Error getting file size for %s: %s", image_path, e)
        raise
