"""Image processing tasks."""

import logging
from pathlib import Path

from PIL import Image

from backend.app.config import settings
from backend.app.services import get_thumbnail_store


def generate_thumbnails(image_path: str, storage_key_stem: str, use_webp: bool = False) -> dict:
    """Generate thumbnails at different sizes and store via ImageStore.

    Also returns original image dimensions to avoid a separate PIL open.

    Args:
        image_path: Path to the original image file (as string for serialization)
        storage_key_stem: UUID stem for naming thumbnails (e.g., "a1b2c3d4e5f6")
        use_webp: If True, save thumbnails as WebP instead of JPEG.

    Returns:
        Dict with 'keys' (size name -> storage key) and 'dimensions' (width, height)
    """
    logger = logging.getLogger(__name__)
    try:
        image_path_obj = Path(image_path)
        thumbnail_store = get_thumbnail_store()
        thumbnail_keys = {}
        ext = "webp" if use_webp else "jpg"

        with Image.open(image_path_obj) as orig:
            # Mode conversion for thumbnail generation.
            # For WebP: preserve RGBA/LA alpha; convert palette and other modes.
            # For JPEG: always convert to RGB (JPEG has no alpha).
            if use_webp:
                if orig.mode == "P":
                    image = orig.convert("RGBA" if "transparency" in orig.info else "RGB")
                elif orig.mode in ("RGBA", "LA"):
                    image = orig  # keep alpha
                elif orig.mode != "RGB":
                    image = orig.convert("RGB")
                else:
                    image = orig
            else:
                image = orig.convert("RGB")

            dimensions = image.size  # (width, height) — capture before thumbnailing

            for idx, (width, height) in enumerate(settings.thumbnail_sizes):
                thumb_key = f"{storage_key_stem}_{width}x{height}.{ext}"
                thumb_path = thumbnail_store.get_path(thumb_key)
                thumb_path.parent.mkdir(parents=True, exist_ok=True)

                thumb = image.copy()
                thumb.thumbnail((width, height), Image.Resampling.LANCZOS)

                if use_webp:
                    thumb.save(thumb_path, format="WEBP", lossless=False, quality=90)
                else:
                    thumb.save(thumb_path, quality=85, optimize=True)
                thumb.close()

                size_name = ["small", "medium", "large"][idx] if idx < 3 else f"size_{idx}"
                thumbnail_keys[size_name] = thumb_key
                logger.debug("Generated %s thumbnail: %s", size_name, thumb_key)

            # Close the converted image if it's a different object from orig
            if image is not orig:
                image.close()

        return {"keys": thumbnail_keys, "dimensions": dimensions}

    except Exception as e:
        logger.error("Error generating thumbnails for %s: %s", image_path, e)
        raise


_THUMBNAIL_SIZE_NAMES = ("small", "medium", "large")


def _fit_within(size: tuple[int, int], box: tuple[int, int]) -> tuple[int, int]:
    """Size that fits ``size`` inside ``box`` preserving aspect ratio, never upscaling."""
    width, height = size
    scale = min(box[0] / width, box[1] / height, 1.0)
    return max(1, round(width * scale)), max(1, round(height * scale))


def write_thumbnails(
    image: Image.Image, storage_key_stem: str, dest_dir: Path
) -> dict[str, tuple[str, Path]]:
    """Write JPEG thumbnails of an already-decoded image into ``dest_dir`` (flat).

    Sizes cascade largest → smallest, each resized from the previous one, so the
    full-resolution image is only resampled once (the current
    ``generate_thumbnails`` copies the original once per size).

    Returns ``{size_name: (thumbnail_key, path)}``. The caller moves the files into
    the thumbnail store (see design/ingest-redesign.md §5.3).
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    rgb = image if image.mode == "RGB" else image.convert("RGB")
    named_sizes = sorted(
        zip(_THUMBNAIL_SIZE_NAMES, settings.thumbnail_sizes, strict=False),
        key=lambda pair: pair[1][0] * pair[1][1],
        reverse=True,
    )
    results: dict[str, tuple[str, Path]] = {}
    source = rgb
    for size_name, (box_w, box_h) in named_sizes:
        target = _fit_within(source.size, (box_w, box_h))
        thumb = (
            source.copy()
            if target == source.size
            else source.resize(target, Image.Resampling.LANCZOS, reducing_gap=3.0)
        )
        key = f"{storage_key_stem}_{box_w}x{box_h}.jpg"
        path = dest_dir / key
        thumb.save(path, format="JPEG", quality=85, optimize=True)
        results[size_name] = (key, path)
        if source is not rgb:
            source.close()
        source = thumb
    if source is not rgb:
        source.close()
    if rgb is not image:
        rgb.close()
    return results


def generate_preview_thumbnail(
    image_path: str,
    staging_dir: str,
    relative_path: str,
    size: int = 120,
    staging_key: str | None = None,
) -> str | None:
    """Generate a small preview thumbnail for the import preview UI.

    Saves the thumbnail into a .thumbs/ subdirectory of the staging dir.
    When ``staging_key`` is provided (UUID-based flat filename), the
    thumbnail is named after its stem.  Otherwise falls back to mangling
    the relative_path for backwards compatibility with tests.

    Args:
        image_path: Absolute path to the source image
        staging_dir: Path to the staging directory (data/staging/{job_id})
        relative_path: Relative path of the file (used for logging/fallback)
        size: Thumbnail size (square, default 120px)
        staging_key: UUID-based staging filename (preferred for naming)

    Returns:
        The safe filename of the generated thumbnail, or None on failure
    """
    logger = logging.getLogger(__name__)
    try:
        thumbs_dir = Path(staging_dir) / ".thumbs"
        thumbs_dir.mkdir(parents=True, exist_ok=True)

        if staging_key:
            safe_name = Path(staging_key).stem + ".jpg"
        else:
            # Legacy fallback: mangle relative_path
            safe_name = relative_path.replace("/", "__").replace("\\", "__")
            safe_name = Path(safe_name).stem + ".jpg"

        thumb_path = thumbs_dir / safe_name

        with Image.open(Path(image_path)) as img:
            with img.convert("RGB") as image:
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
    logger = logging.getLogger(__name__)
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
    logger = logging.getLogger(__name__)
    try:
        return Path(image_path).stat().st_size
    except Exception as e:
        logger.error("Error getting file size for %s: %s", image_path, e)
        raise
