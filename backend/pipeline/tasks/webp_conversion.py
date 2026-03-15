"""WebP conversion helper for the import pipeline.

Converts a staged image file to WebP in-place (original is deleted).
Returns the new file path, or the original path unchanged if conversion
is skipped (video, already-WebP, animated GIF).
"""

import logging
from pathlib import Path

from PIL import Image

logger = logging.getLogger(__name__)

_VIDEO_EXTENSIONS = {".mp4", ".webm", ".mov", ".avi"}


def should_skip_conversion(path: Path) -> bool:
    """Return True if WebP conversion should be skipped for this file.

    Skips: videos (by extension), files already in WebP format, animated GIFs.
    """
    ext = path.suffix.lower()
    if ext in _VIDEO_EXTENSIONS:
        return True
    if ext == ".webp":
        return True
    if ext == ".gif":
        try:
            with Image.open(path) as img:
                # n_frames > 1 catches properly-encoded animated GIFs.
                # 'loop' in info catches GIFs saved with a NETSCAPE loop block
                # even when Pillow collapses visually-identical frames to 1.
                return getattr(img, "n_frames", 1) > 1 or "loop" in img.info
        except Exception:
            return True  # Can't open — skip safely
    return False


def _prepare_mode(img: Image.Image) -> Image.Image:
    """Convert image to a mode compatible with WebP encoding."""
    mode = img.mode
    if mode == "P":
        has_transparency = "transparency" in img.info
        return img.convert("RGBA" if has_transparency else "RGB")
    if mode == "CMYK":
        return img.convert("RGB")
    if mode == "RGBA":
        return img  # Preserve alpha as-is
    if mode == "LA":
        return img.convert("RGBA")  # Pillow WebP encoder has no LA mode; RGBA preserves alpha
    if mode != "RGB":
        return img.convert("RGB")
    return img


def convert_to_webp(path: Path, lossless: bool = True, method: int = 4) -> Path:
    """Convert image at *path* to WebP, returning the new file path.

    If conversion is skipped (video / already-WebP / animated GIF), the
    original *path* is returned unchanged and no files are modified.

    Otherwise:
    - Converts and saves as ``<stem>.webp`` in the same directory.
    - Deletes the original file.
    - Returns the new ``.webp`` path.

    Args:
        path: Absolute path to the source image.
        lossless: Use lossless WebP encoding (default: True).
        method: Pillow WebP encode method 0–6; 4 balances speed and compression.
    """
    if should_skip_conversion(path):
        return path

    webp_path = path.with_suffix(".webp")

    try:
        with Image.open(path) as img:
            converted = _prepare_mode(img)
            converted.save(str(webp_path), format="WEBP", lossless=lossless, method=method)
            if converted is not img:
                converted.close()

        path.unlink()  # Delete original after successful save
        logger.debug("Converted %s → %s", path.name, webp_path.name)
        return webp_path

    except Exception:
        logger.exception("WebP conversion failed for %s — keeping original", path)
        if webp_path.exists():
            webp_path.unlink()
        return path  # Fall through with original on failure
