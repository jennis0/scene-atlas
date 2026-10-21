"""Which grids re-detection may change (ADR-019, design/grid-detection-v3.md).

Shared by the grid backfill and the refresh of an edited linked file
(design/library-setup.md §4.5): neither ever overwrites a grid set by hand, a file name
that says "no grid", or a file name's exact NxM. Those were the most reliable labels in
evaluation.
"""

from __future__ import annotations

from typing import Literal, Protocol, cast

from sqlalchemy.orm import Session

from backend.app.models.database import (
    GRID_SOURCE_DETECTOR,
    GRID_SOURCE_FILENAME,
    GRID_SOURCE_USER,
    Image,
)

DetectionMode = Literal["full", "size"]


class GridState(Protocol):
    """An image's type and grid columns, as stored (an ``Image`` row, or a snapshot)."""

    @property
    def image_type(self) -> str | None: ...
    @property
    def media_type(self) -> str | None: ...
    @property
    def gridded(self) -> bool | None: ...
    @property
    def grid_width(self) -> int | None: ...
    @property
    def grid_confidence(self) -> float | None: ...
    @property
    def grid_source(self) -> str | None: ...


def detection_mode(image: Image | GridState, force: bool) -> DetectionMode | None:
    """``"full"`` (presence and size), ``"size"`` (size only), or None to leave the grid.

    - no grid information → full;
    - the file name says gridded but gives no size → size only;
    - previously detected → re-detected only with ``force``;
    - never: scenes, videos, user grids, "no grid" names and a name's exact NxM.
    """
    if image.image_type != "battlemap" or image.media_type == "video":
        return None
    if image.grid_source == GRID_SOURCE_USER:
        return None
    if image.grid_source == GRID_SOURCE_FILENAME:
        # A confidence means the size was detected; without one, any size is the file's NxM.
        if image.gridded is not True or (
            image.grid_width is not None and image.grid_confidence is None
        ):
            return None  # explicit "no grid", or an exact NxM
        return "size" if force or image.grid_confidence is None else None
    if image.grid_source == GRID_SOURCE_DETECTOR:
        return "full" if force else None
    return "full"  # no grid information yet


def group_sibling_counts(
    db: Session, image_id: int, group_id: int | None
) -> tuple[tuple[int, int], ...]:
    """NxM grid sizes from the file names of other images in the same group, both
    orientations: candidates for size-only detection, never truth."""
    if group_id is None:
        return ()
    rows = (
        db.query(Image.grid_width, Image.grid_height)
        .filter(
            Image.group_id == group_id,
            Image.id != image_id,
            Image.grid_source == GRID_SOURCE_FILENAME,
            Image.grid_width.isnot(None),
            Image.grid_height.isnot(None),
        )
        .distinct()
        .all()
    )
    counts: dict[tuple[int, int], None] = {}
    for w, h in cast(list[tuple[int, int]], rows):
        counts[(w, h)] = None
        counts[(h, w)] = None
    return tuple(counts)
