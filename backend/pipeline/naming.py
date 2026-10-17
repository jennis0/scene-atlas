"""Shared filename and export-path helpers.

Used by both the groups API (per-group ZIP download) and the export pipeline
(full library export) so the naming logic stays in one place.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.app.models.database import Image

_UNSAFE = re.compile(r'[/\\:*?"<>|]')
_SPACES = re.compile(r"\s+")


def sanitize_segment(s: str) -> str:
    """Replace filesystem-unsafe characters with a space and collapse whitespace."""
    return _SPACES.sub(" ", _UNSAFE.sub(" ", s)).strip()


def download_filename(img: Image, group_name: str) -> str:
    """Build the human-readable download filename for a single image.

    Format: [Group - ][Subgroup - ]Name - Grid WxH | Hex WxH | No Grid + ext

    Mirrors the frontend ``buildDownloadFilename`` function exactly.
    """
    parts: list[str] = []
    if group_name and group_name != (img.name or ""):
        parts.append(sanitize_segment(group_name))
    if img.subgroup:
        parts.append(sanitize_segment(img.subgroup))
    parts.append(sanitize_segment(img.name or ""))
    if img.gridded:
        label = "Hex" if img.grid_type == "hex" else "Grid"
        dims = f" {img.grid_width}x{img.grid_height}" if img.grid_width and img.grid_height else ""
        parts.append(f"{label}{dims}")
    else:
        parts.append("No Grid")
    # The stored file's extension, which differs from the upload's after conversion.
    return " - ".join(parts) + Path(img.storage_key or img.filename).suffix


def export_path(img: Image, group_name: str | None, author: str | None) -> str:
    """Return the full relative export path for an image.

    Structure:
        Author/Group/[Subgroup/]filename   — for grouped images
        Author/_Ungrouped/filename          — for images with no group

    The author and group folders are sanitized; ``_Ungrouped`` is a literal
    sentinel so it sorts clearly apart from real group names.
    """
    author_seg = sanitize_segment(author) if author and author.strip() else "Unknown"
    filename = download_filename(img, group_name or "")

    if group_name:
        group_seg = sanitize_segment(group_name)
        if img.subgroup:
            return f"{author_seg}/{group_seg}/{sanitize_segment(img.subgroup)}/{filename}"
        return f"{author_seg}/{group_seg}/{filename}"

    return f"{author_seg}/_Ungrouped/{filename}"


def unique_export_path(img: Image, seen: set[str]) -> str:
    """``export_path`` for *img*, suffixed `` (2)``, `` (3)``… if already in *seen*; records it."""
    arc = export_path(img, img.group.base_name if img.group else None, img.author)
    if arc in seen:
        path = Path(arc)
        n = 2
        while f"{path.parent}/{path.stem} ({n}){path.suffix}" in seen:
            n += 1
        arc = f"{path.parent}/{path.stem} ({n}){path.suffix}"
    seen.add(arc)
    return arc


def export_metadata(img: Image) -> dict:
    """The ``metadata.json`` entry for one exported image."""
    tags_by_cat: dict[str, list[str]] = {}
    for tag in img.tags:
        tags_by_cat.setdefault(tag.category, []).append(tag.value)
    return {
        "image_type": img.image_type or "battlemap",
        "gridded": bool(img.gridded),
        "grid_type": img.grid_type,
        "grid_width": img.grid_width,
        "grid_height": img.grid_height,
        "tags": tags_by_cat,
    }
