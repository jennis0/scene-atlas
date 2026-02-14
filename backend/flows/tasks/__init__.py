"""Prefect tasks package."""

from .color_extraction import extract_dominant_colors
from .embedding_generation import generate_clip_embedding
from .image_processing import generate_thumbnails, get_file_size, get_image_dimensions
from .metadata_extraction import (
    extract_tags_from_filename,
    extract_tags_from_path,
    infer_author,
    infer_base_name,
    merge_tags,
)

__all__ = [
    "extract_dominant_colors",
    "generate_clip_embedding",
    "generate_thumbnails",
    "get_file_size",
    "get_image_dimensions",
    "extract_tags_from_filename",
    "extract_tags_from_path",
    "infer_author",
    "infer_base_name",
    "merge_tags",
]
