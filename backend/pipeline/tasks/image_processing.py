"""Thumbnail generation for the ingest pipeline."""

from pathlib import Path

from PIL import Image

from backend.app.config import settings

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
    full-resolution image is only resampled once.

    Returns ``{size_name: (thumbnail_key, path)}``. The caller moves the files into
    the thumbnail store (see design/ingestion.md §5.3).
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
