"""Thumbnail generation for the ingest pipeline."""

from pathlib import Path

from PIL import Image

from backend.app.config import settings

_THUMBNAIL_SIZE_NAMES = ("small", "medium", "large")

# Opaque thumbnails are JPEG; thumbnails with transparent pixels are WebP so the
# alpha channel survives (flattening it turned transparent areas black). Opaque
# images stay JPEG because it encodes several times faster than WebP and keeps
# existing libraries uniform. See design/storage.md "Keys".
_JPEG_OPTIONS = {"format": "JPEG", "quality": 85, "optimize": True}
_WEBP_OPTIONS = {"format": "WEBP", "quality": 85, "method": 4}


def _fit_within(size: tuple[int, int], box: tuple[int, int]) -> tuple[int, int]:
    """Size that fits ``size`` inside ``box`` preserving aspect ratio, never upscaling."""
    width, height = size
    scale = min(box[0] / width, box[1] / height, 1.0)
    return max(1, round(width * scale)), max(1, round(height * scale))


def _may_have_alpha(image: Image.Image) -> bool:
    return image.mode in ("RGBA", "LA", "PA", "La", "RGBa") or "transparency" in image.info


def _working_copy(image: Image.Image) -> Image.Image:
    """``image`` as RGB, or RGBA when it can carry transparency (alpha band or tRNS key)."""
    target = "RGBA" if _may_have_alpha(image) else "RGB"
    return image if image.mode == target else image.convert(target)


def _has_transparency(image: Image.Image) -> bool:
    return image.mode == "RGBA" and image.getchannel("A").getextrema()[0] < 255


def write_thumbnails(
    image: Image.Image, storage_key_stem: str, dest_dir: Path
) -> dict[str, tuple[str, Path]]:
    """Write thumbnails of an already-decoded image into ``dest_dir`` (flat).

    Sizes cascade largest → smallest, each resized from the previous one, so the
    full-resolution image is only resampled once. Thumbnails are JPEG, or RGBA
    WebP when the image has transparent pixels (all sizes share one format).

    Returns ``{size_name: (thumbnail_key, path)}``. The caller moves the files into
    the thumbnail store (see design/ingestion.md §5.3).
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    working = _working_copy(image)
    named_sizes = sorted(
        zip(_THUMBNAIL_SIZE_NAMES, settings.thumbnail_sizes, strict=False),
        key=lambda pair: pair[1][0] * pair[1][1],
        reverse=True,
    )
    results: dict[str, tuple[str, Path]] = {}
    source = working
    first = True
    for size_name, (box_w, box_h) in named_sizes:
        target = _fit_within(source.size, (box_w, box_h))
        thumb = (
            source.copy()
            if target == source.size
            else source.resize(target, Image.Resampling.LANCZOS, reducing_gap=3.0)
        )
        if first and thumb.mode == "RGBA" and not _has_transparency(thumb):
            # RGBA but fully opaque (common for PNG exports): no alpha to keep.
            # Decided once, on the largest size, so every size shares a format.
            opaque = thumb.convert("RGB")
            thumb.close()
            thumb = opaque
        first = False
        if thumb.mode == "RGBA":
            key = f"{storage_key_stem}_{box_w}x{box_h}.webp"
            options = _WEBP_OPTIONS
        else:
            key = f"{storage_key_stem}_{box_w}x{box_h}.jpg"
            options = _JPEG_OPTIONS
        path = dest_dir / key
        thumb.save(path, **options)
        results[size_name] = (key, path)
        if source is not working:
            source.close()
        source = thumb
    if source is not working:
        source.close()
    if working is not image:
        working.close()
    return results
