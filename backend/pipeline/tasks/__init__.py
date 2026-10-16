"""Per-image processing tasks (thumbnails, colors, CLIP, grids)."""

from .color_extraction import extract_dominant_colors
from .image_processing import write_thumbnails

__all__ = [
    "extract_dominant_colors",
    "write_thumbnails",
]
