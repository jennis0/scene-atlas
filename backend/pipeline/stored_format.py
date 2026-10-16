"""Convert imported images to the configured storage format (design/ingestion.md §10).

An image is stored unchanged when converting would lose something or can't be
done (``skip_reason``). Lossy sources never become lossless WebP: that makes
JPEGs about three times larger.
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


@dataclass(frozen=True)
class StoredFormat:
    """The storage-format settings that apply to one batch."""

    format: str = FORMAT_ORIGINAL
    quality: int = 90
    lossless: bool = True


def skip_reason(image: PILImage.Image, target: str) -> str | None:
    """Why ``image`` should be stored unchanged instead of converted to ``target``, or None."""
    if _PIL_FORMAT[target] == _source_format(image):
        return "already in the target format"  # re-encoding would only lose quality
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
        lossy_source = _source_format(image) == "JPEG"
        icc_profile = image.info.get("icc_profile")
        image.load()
        out = _normalise_mode(image, spec.format)
        dest = dest_dir / f"{stem}{_SUFFIX[spec.format]}"
        options: dict = {"icc_profile": icc_profile} if icc_profile else {}
        if spec.format == "webp":
            options["exact"] = True  # keep RGB under transparent pixels
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


def _source_format(image: PILImage.Image) -> str:
    fmt = (image.format or "").upper()
    return "JPEG" if fmt == "MPO" else fmt  # MPO is multi-picture JPEG


def _has_alpha(image: PILImage.Image) -> bool:
    return image.mode in ("RGBA", "LA", "PA") or "transparency" in image.info


def _normalise_mode(image: PILImage.Image, target: str) -> PILImage.Image:
    if target == "jpeg":
        return image if image.mode in ("RGB", "L", "CMYK") else image.convert("RGB")
    if target == "webp":
        if image.mode in ("RGB", "RGBA"):
            return image
        return image.convert("RGBA" if _has_alpha(image) else "RGB")
    # PNG writes most modes; CMYK and YCbCr it can't.
    return image.convert("RGB") if image.mode in ("CMYK", "YCbCr") else image
