"""Settle a file name's NxM grid size against the image it labels (design/parser.md §2).

The parser sees only the path, so it reports the size in name order, plus alternative
readings where a digit may be glued on ("Destroyed630x50" is probably variant 6 at
30x50). Once ingest knows the pixel size, cells should come out roughly square:
that picks the reading and whether N is columns or rows.
"""

from __future__ import annotations

import math

# Images within 2% of square give no reliable orientation; the name's order is kept.
_SQUARE_TOLERANCE = 50
# A literal reading is replaced only when its cells are clearly not square for this
# image, and only by an alternative whose cells clearly are. Across the 282 real files
# with a 3-digit side (2026-10), the readings picked measured 1.00-1.17 and the literal
# readings they replaced 1.82 and more; real sizes like 100x100 and 70x108 fit as read.
_LITERAL_MAX_SKEW = math.log(1.5)
_ALTERNATIVE_MAX_SKEW = math.log(1.25)


def _orient(grid_width: int, grid_height: int, width: int, height: int) -> tuple[int, int]:
    if abs(width - height) * _SQUARE_TOLERANCE <= max(width, height):
        return grid_width, grid_height
    if (grid_width > grid_height) != (width > height):
        return grid_height, grid_width
    return grid_width, grid_height


def orient_grid(
    grid_width: int | None, grid_height: int | None, width: int | None, height: int | None
) -> tuple[int | None, int | None]:
    """Order an NxM so the longer side of the grid runs along the longer side of the
    image. Names disagree on whether N is columns or rows ("30x20" on a portrait map),
    and cells far from square are never what the creator meant."""
    if not (grid_width and grid_height and width and height):
        return grid_width, grid_height
    return _orient(grid_width, grid_height, width, height)


def _cell_skew(grid_width: int, grid_height: int, width: int, height: int) -> float:
    """How far cells are from square, as |log(cell width / cell height)|."""
    return abs(math.log((width / grid_width) / (height / grid_height)))


def filename_grid_counts(parsed: dict, width: int | None, height: int | None) -> dict:
    """``grid_width`` / ``grid_height`` for an image, from its parsed file name."""
    grid_width, grid_height = parsed.get("grid_width"), parsed.get("grid_height")
    if not (grid_width and grid_height and width and height):
        return {"grid_width": grid_width, "grid_height": grid_height}
    chosen = _orient(grid_width, grid_height, width, height)
    alternatives = [
        _orient(w, h, width, height) for w, h in parsed.get("grid_size_alternatives") or ()
    ]
    best = min(alternatives, key=lambda size: _cell_skew(*size, width, height), default=chosen)
    if (
        _cell_skew(*chosen, width, height) > _LITERAL_MAX_SKEW
        and _cell_skew(*best, width, height) <= _ALTERNATIVE_MAX_SKEW
    ):
        chosen = best
    return {"grid_width": chosen[0], "grid_height": chosen[1]}
