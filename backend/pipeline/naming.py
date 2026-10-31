"""Shared filename and export-path helpers.

The readable layout (``ReadableLayout``, below) is how every export names files
(design/export-backup-move.md §3). ``download_filename``, ``export_path`` and
``unique_export_path`` are the older layout, used until the download endpoint and the
folder export move to it.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
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
        # Zip entry names always use '/': a Path would rejoin them with '\' on Windows.
        path = PurePosixPath(arc)
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


# The readable layout (design/export-backup-move.md §3): every writer of files (downloads,
# the full export, rebuild's set-aside folder) names them here. The names are for people;
# the metadata travels in scene-atlas.jsonl, so nothing is parsed back out of them.

FOLDER_MAX = 80
FILE_MAX = 150
PATH_MAX = 259  # Windows' MAX_PATH, less the terminating NUL
_MIN_STEM = 8  # never shorten a name below this, whatever the path budget says
_SEP = "_"
_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"{p}{i}" for p in ("COM", "LPT") for i in range(1, 10)}


def layout_segment(s: str | None) -> str:
    """One part of a readable name: unsafe characters, and ``_`` (the separator between
    parts), become spaces."""
    return sanitize_segment((s or "").replace(_SEP, " "))


def _safe_stem(stem: str) -> str:
    """Windows refuses trailing dots and spaces, and reserved device names."""
    stem = stem.rstrip(". ")
    if stem.split(".", 1)[0].upper() in _RESERVED:
        stem += "-"
    return stem or "image"


def grid_code(
    gridded: bool | None, grid_type: str | None, width: int | None, height: int | None
) -> str:
    """``G30x30`` / ``HG20x15`` (``G`` / ``HG`` with no size), ``GL`` for gridless, and
    nothing when it isn't known whether there is a grid."""
    if gridded is None:
        return ""
    if not gridded:
        return "GL"
    code = "HG" if grid_type == "hex" else "G"
    return f"{code}{width}x{height}" if width and height else code


@dataclass(frozen=True)
class LayoutImage:
    """What the layout needs to know about one image."""

    name: str | None
    subgroup: str | None
    grid: str  # grid_code()
    tags: tuple[str, ...]  # values, in category order
    ext: str  # with the dot, ".webp"


def _tag_text(value: str) -> str:
    """A tag value inside ``[a,b]``: its own commas and brackets would read as structure."""
    return sanitize_segment(layout_segment(value).translate(str.maketrans(",[]", "   ")))


def layout_image(img: Image, category_order: Mapping[str, int] | None = None) -> LayoutImage:
    """``LayoutImage`` for an ORM image, its tags in *category_order* (category → rank)."""
    order = category_order or {}
    tags = sorted(
        img.tags, key=lambda t: (order.get(t.category, len(order)), t.category, _tag_text(t.value))
    )
    return LayoutImage(
        name=img.name,
        subgroup=img.subgroup,
        grid=grid_code(img.gridded, img.grid_type, img.grid_width, img.grid_height),
        tags=tuple(dict.fromkeys(_tag_text(t.value) for t in tags)),
        # The stored file's extension, which differs from the upload's after conversion.
        ext=Path(img.storage_key or img.filename).suffix,
    )


def readable_stem(
    author: str | None,
    group: str | None,
    subgroup: str | None,
    name: str | None,
    grid: str,
    tags: Sequence[str],
    limit: int,
) -> str:
    """``Author_Group_[Subgroup_]Name_Grid[tags]``, at most *limit* characters.

    Missing parts are left out, and a name equal to its group's isn't repeated. Too long:
    tags are dropped from the end, then the name is shortened, then the group, then the
    whole thing."""
    parts = {
        "author": layout_segment(author),
        "group": layout_segment(group),
        "subgroup": layout_segment(subgroup),
        "name": layout_segment(name),
    }
    if parts["name"].casefold() == parts["group"].casefold():
        parts["name"] = ""
    tags = [t for t in tags if t]

    def build() -> str:
        stem = _SEP.join(p for p in (*parts.values(), grid) if p)
        return stem + (f"[{','.join(tags)}]" if tags else "")

    while len(build()) > limit and tags:
        tags.pop()
    for key in ("name", "group"):
        excess = len(build()) - limit
        if excess > 0 and parts[key]:
            parts[key] = parts[key][: max(1, len(parts[key]) - excess)].rstrip()
    return _safe_stem(build()[:limit])


class ReadableLayout:
    """Places images in the readable layout, keeping every path distinct.

    A group of two or more images gets a folder, ``Author_Group``; a group of one, and
    ungrouped images, sit at the top level. Names are compared case-insensitively, since
    Windows and macOS (and zip extractors there) do. A clash gets `` (2)``, `` (3)``… in
    the order things are placed, so callers place groups in id order and each group's
    images in id order. *taken* are top-level names already on disk (a resumed export);
    *root_len* is the length of the folder the layout is written into, which counts
    against Windows' path limit.
    """

    def __init__(self, *, root_len: int = 0, taken: Iterable[str] = ()):
        self._root_len = root_len
        self._top: set[str] = {t.casefold() for t in taken}
        self._in_folder: dict[str, set[str]] = {}

    def place_group(
        self, group_name: str | None, author: str | None, images: Sequence[LayoutImage]
    ) -> list[str]:
        """The relative (``/``-separated) path of each of *images*, in order."""
        if group_name is None or len(images) == 1:
            return [self._file(None, self._top, author, group_name, img) for img in images]
        folder_limit = min(FOLDER_MAX, PATH_MAX - self._root_len - 1 - _MIN_STEM)
        folder_limit = max(folder_limit, _MIN_STEM)
        joined = _SEP.join(p for p in (layout_segment(author), layout_segment(group_name)) if p)
        folder = _unique(self._top, _safe_stem(joined[:folder_limit]), "", folder_limit)
        names = self._in_folder.setdefault(folder, set())
        return [f"{folder}/{self._file(folder, names, author, group_name, img)}" for img in images]

    def _file(
        self,
        folder: str | None,
        names: set[str],
        author: str | None,
        group_name: str | None,
        img: LayoutImage,
    ) -> str:
        used = self._root_len + 1 + (len(folder) + 1 if folder else 0)
        limit = max(min(FILE_MAX, PATH_MAX - used) - len(img.ext), _MIN_STEM)
        stem = readable_stem(author, group_name, img.subgroup, img.name, img.grid, img.tags, limit)
        return _unique(names, stem, img.ext, limit)


def _unique(taken: set[str], stem: str, ext: str, limit: int) -> str:
    """``stem + ext``, or ``stem (n) + ext`` for the first n that isn't in *taken* (compared
    case-insensitively), shortening *stem* so the result keeps within *limit*; records it."""
    candidate, n = stem, 1
    while (candidate + ext).casefold() in taken:
        n += 1
        suffix = f" ({n})"
        candidate = _safe_stem(stem[: limit - len(suffix)]) + suffix
    taken.add((candidate + ext).casefold())
    return candidate + ext
