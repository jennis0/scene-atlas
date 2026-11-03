"""Names for exported files: ``sanitize_segment``, and the readable layout
(``ReadableLayout``), which every export names files by (design/export-backup-move.md §3).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.app.models.database import Image, ImageGroup

# Also control characters, which Windows refuses in names
_UNSAFE = re.compile(r'[/\\:*?"<>|\x00-\x1f\x7f]')
_SPACES = re.compile(r"\s+")


def sanitize_segment(s: str) -> str:
    """Replace filesystem-unsafe characters with a space and collapse whitespace."""
    return _SPACES.sub(" ", _UNSAFE.sub(" ", s)).strip()


# The readable layout (design/export-backup-move.md §3): every writer of files (downloads,
# the full export, rebuild's set-aside folder) names them here. The names are for people;
# the metadata travels in scene-atlas.jsonl, so nothing is parsed back out of them.

FOLDER_MAX = 80
FILE_MAX = 150
PATH_MAX = 259  # Windows' MAX_PATH, less the terminating NUL, in UTF-16 units
_TEMP_SUFFIX = len(".part")  # writers write a file as <name>.part first
_MIN_STEM = 8  # never shorten a name below this, whatever the path budget says
_SEP = "_"
_RESERVED = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"} | {
    f"{p}{i}" for p in ("COM", "LPT") for i in [*"0123456789", "¹", "²", "³"]
}


def _u16(s: str) -> int:
    """Length as Windows counts it (UTF-16 units: an emoji is two)."""
    return len(s.encode("utf-16-le")) // 2


def layout_segment(s: str | None) -> str:
    """One part of a readable name: unsafe characters, and ``_`` (the separator between
    parts), become spaces. NFC, so a name typed on macOS (NFD) and one typed on Windows
    are the same name, as macOS' file systems treat them."""
    return sanitize_segment(unicodedata.normalize("NFC", (s or "").replace(_SEP, " ")))


def _safe_stem(stem: str, limit: int = FILE_MAX) -> str:
    """Windows refuses trailing dots and spaces, and reserved device names. At most
    *limit* characters."""
    stem = stem[:limit].rstrip(". ")
    if stem.split(".", 1)[0].upper() in _RESERVED:
        stem = stem[: limit - 1] + "-"
    return stem or "image"


_EXT = re.compile(r"\.[A-Za-z0-9]{1,10}")


def _extension(name: str) -> str:
    """*name*'s extension when it is a plain one (``.webp``), else none."""
    suffix = PurePosixPath(name.replace("\\", "/")).suffix
    return suffix if _EXT.fullmatch(suffix) else ""


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
        ext=_extension(img.storage_key or img.filename),
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
    return _safe_stem(build(), limit)


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
        self._top = _Names(taken)
        self._in_folder: dict[str, _Names] = {}

    def place_group(
        self, group_name: str | None, author: str | None, images: Sequence[LayoutImage]
    ) -> list[str]:
        """The relative (``/``-separated) path of each of *images*, in order."""
        if group_name is None or len(images) == 1:
            return [self._file(None, self._top, author, group_name, img) for img in images]
        folder_limit = min(FOLDER_MAX, PATH_MAX - _TEMP_SUFFIX - self._root_len - 1 - _MIN_STEM)
        folder_limit = max(folder_limit, _MIN_STEM)
        joined = _SEP.join(p for p in (layout_segment(author), layout_segment(group_name)) if p)
        folder = self._top.claim(_safe_stem(joined, folder_limit), "", folder_limit)
        names = self._in_folder.setdefault(folder, _Names())
        return [f"{folder}/{self._file(folder, names, author, group_name, img)}" for img in images]

    def place_images(
        self,
        group: ImageGroup | None,
        images: Sequence[Image],
        category_order: Mapping[str, int] | None = None,
    ) -> list[str]:
        """``place_group`` for ORM images: under their group's name and author, or, for
        ungrouped images, each under its own author."""
        if group is None:
            return [
                self.place_group(None, img.author, [layout_image(img, category_order)])[0]
                for img in images
            ]
        layout = [layout_image(img, category_order) for img in images]
        return self.place_group(group.base_name, group.author, layout)

    def _file(
        self,
        folder: str | None,
        names: _Names,
        author: str | None,
        group_name: str | None,
        img: LayoutImage,
    ) -> str:
        budget = PATH_MAX - _TEMP_SUFFIX - self._root_len - 1 - (_u16(folder) + 1 if folder else 0)
        limit = max(min(FILE_MAX, budget) - len(img.ext), _MIN_STEM)
        while True:
            stem = readable_stem(
                author, group_name, img.subgroup, img.name, img.grid, img.tags, limit
            )
            # Characters outside the BMP count twice towards Windows' limit
            excess = _u16(stem) + _u16(img.ext) - budget
            if excess <= 0 or limit <= _MIN_STEM:
                return names.claim(stem, img.ext, limit)
            limit = max(limit - excess, _MIN_STEM)


class _Names:
    """The names taken in one folder, compared as Windows and macOS do: ignoring case and
    Unicode normalisation."""

    def __init__(self, taken: Iterable[str] = ()):
        self._taken = {_key(t) for t in taken}
        self._next: dict[str, int] = {}  # a name → the next ` (n)` to try for it

    def claim(self, stem: str, ext: str, limit: int) -> str:
        """``stem + ext``, or ``stem (n) + ext`` for the first n not taken, shortening
        *stem* so the result keeps within *limit*; records it."""
        base = _key(stem + ext)
        candidate = stem
        if base in self._taken:
            n = self._next.get(base, 2)
            while True:
                suffix = f" ({n})"
                candidate = _safe_stem(stem, limit - len(suffix)) + suffix
                n += 1
                if _key(candidate + ext) not in self._taken:
                    break
            self._next[base] = n
        self._taken.add(_key(candidate + ext))
        return candidate + ext


def _key(name: str) -> str:
    return unicodedata.normalize("NFC", name).casefold()
