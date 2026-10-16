"""Optional conversion of imported images to a configured storage format (design §10).

The library keeps the original file unless the ``stored_format`` setting asks for
another format. Conversion works on a worker-owned temp copy and never touches
the staged upload. Hashes used for duplicate detection (``source_hash``,
``pixel_hash``) always come from the source, so they work the same whatever the
storage format.

An image is stored unchanged, even when a format is configured, if converting it
would lose something or can't be done:

- it is already in the target format (re-encoding a JPEG only loses quality);
- it is animated (only the first frame would survive);
- it has transparency and the target is JPEG;
- it is wider or taller than WebP allows, for a WebP target.

Lossy sources are never encoded as lossless WebP, which makes JPEGs about three
times larger (Phase 0 findings); they use ``stored_quality`` instead.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from PIL import Image as PILImage

logger = logging.getLogger(__name__)

FORMAT_ORIGINAL = "original"
STORED_FORMATS = (FORMAT_ORIGINAL, "webp", "jpeg", "png")

_PIL_FORMAT = {"webp": "WEBP", "jpeg": "JPEG", "png": "PNG"}
_SUFFIX = {"webp": ".webp", "jpeg": ".jpg", "png": ".png"}

WEBP_MAX_DIM = 16383
# Source formats that can only hold lossy data; lossless output would just inflate them.
_LOSSY_SOURCES = {"JPEG", "MPO"}


@dataclass(frozen=True)
class StoredFormat:
    """The storage-format settings that apply to one batch."""

    format: str = FORMAT_ORIGINAL
    quality: int = 90
    lossless: bool = True


def skip_reason(image: PILImage.Image, target: str) -> str | None:
    """Why ``image`` should be stored unchanged instead of converted to ``target``, or None."""
    source = (image.format or "").upper()
    if _PIL_FORMAT[target] == source or (target == "jpeg" and source == "MPO"):
        return "already in the target format"
    if getattr(image, "n_frames", 1) > 1:
        return "animated"
    if target == "jpeg" and _has_alpha(image):
        return "has transparency"
    if target == "webp" and max(image.size) > WEBP_MAX_DIM:
        return "too large for WebP"
    return None


def convert(source: Path, dest_dir: Path, stem: str, spec: StoredFormat) -> Path | None:
    """Write ``source`` in the configured format to ``dest_dir/<stem><suffix>``.

    Returns the new file, or None when the original should be stored as is.
    """
    if spec.format == FORMAT_ORIGINAL:
        return None
    with PILImage.open(source) as image:
        reason = skip_reason(image, spec.format)
        if reason:
            logger.debug("Storing %s unconverted: %s", source.name, reason)
            return None
        lossy_source = (image.format or "").upper() in _LOSSY_SOURCES
        icc_profile = image.info.get("icc_profile")
        image.load()
        out = _normalise_mode(image, spec.format)
        dest = dest_dir / f"{stem}{_SUFFIX[spec.format]}"
        options: dict = {"icc_profile": icc_profile} if icc_profile else {}
        if spec.format == "webp":
            options["exact"] = True  # keep RGB under transparent pixels (pixel_hash relies on it)
            if spec.lossless and not lossy_source:
                options["lossless"] = True
            else:
                options["quality"] = spec.quality
        elif spec.format == "jpeg":
            options["quality"] = spec.quality
        try:
            out.save(dest, _PIL_FORMAT[spec.format], **options)
        except BaseException:
            dest.unlink(missing_ok=True)
            raise
        finally:
            if out is not image:
                out.close()
    return dest


def _has_alpha(image: PILImage.Image) -> bool:
    return image.mode in ("RGBA", "LA", "PA") or "transparency" in image.info


def _normalise_mode(image: PILImage.Image, target: str) -> PILImage.Image:
    """Convert to a mode the target format can write."""
    if target == "jpeg":
        return image if image.mode in ("RGB", "L", "CMYK") else image.convert("RGB")
    if target == "webp":
        if image.mode in ("RGB", "RGBA"):
            return image
        return image.convert("RGBA" if _has_alpha(image) else "RGB")
    # PNG writes most modes; CMYK and YCbCr it can't.
    return image.convert("RGB") if image.mode in ("CMYK", "YCbCr") else image
