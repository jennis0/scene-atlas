"""Refreshing a linked image whose file was edited in place (design/library-setup.md §4.5).

A rescan that finds a file changed (same key, different size or mtime) queues a
**refresh** item for its image, in the scan's job like a new file. The worker claims it
with a snapshot of the image (``RefreshTarget``), then:

- hashes the file. The same bytes as the image (only touched): the file's version is
  recorded and nothing else happens;
- otherwise decodes it, makes new thumbnails, colours, hashes and an embedding, and
  re-detects the grid where the rules allow (``refresh_grid``);
- commits by updating the image in place (``ingest_process``): only columns that come
  from the file change. Name, author, tags, group and type are the user's.

The edited bytes may be another image's (a byte or pixel duplicate): the image is still
refreshed in place, because the user's file is the truth, and the library then holds
two images with the same bytes, as "Import as copy" can make.

A failed refresh leaves the image as it was. An image removed while its refresh is under
way is skipped at commit (``REFRESH_GONE_REASON``).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from backend.app.models import Image
from backend.app.models.database import GRID_SOURCE_DETECTOR, GRID_SOURCE_FILENAME

from .filename_grid import orient_grid
from .grid_rules import DetectionMode, detection_mode, group_sibling_counts
from .pipeline_config import PipelineConfig
from .tasks import grid_detection

REFRESH_GONE_REASON = "The map was removed before its file could be refreshed"
# error_kind of a refresh skipped because its image went
KIND_REFRESH_GONE = "refresh_gone"

GridColumns = dict[str, object]


@dataclass(frozen=True)
class RefreshTarget:
    """The image a refresh item updates, as it was when the item was claimed. Its grid
    columns decide what re-detection may change; commit only writes a grid if they are
    still the same (a user edit in between wins)."""

    image_id: int
    content_hash: str | None
    image_type: str | None
    media_type: str | None
    gridded: bool | None
    grid_width: int | None
    grid_height: int | None
    grid_type: str | None
    grid_confidence: float | None
    grid_source: str | None
    sibling_counts: tuple[tuple[int, int], ...] = ()

    @classmethod
    def of(cls, image: Image, sibling_counts: tuple[tuple[int, int], ...] = ()) -> RefreshTarget:
        return cls(
            image_id=image.id,
            content_hash=image.content_hash,
            image_type=image.image_type,
            media_type=image.media_type,
            gridded=image.gridded,
            grid_width=image.grid_width,
            grid_height=image.grid_height,
            grid_type=image.grid_type,
            grid_confidence=image.grid_confidence,
            grid_source=image.grid_source,
            sibling_counts=sibling_counts,
        )


def grid_snapshot(image: Image | RefreshTarget) -> tuple:
    """What a grid decision was made from: the type and every grid column."""
    return (
        image.image_type,
        image.gridded,
        image.grid_width,
        image.grid_height,
        image.grid_type,
        image.grid_confidence,
        image.grid_source,
    )


def load_targets(db: Session, file_ids: Iterable[int]) -> dict[int, RefreshTarget]:
    """file id → its image's snapshot, for linked files that already are an image's: an
    item for such a file is a refresh. One query, plus one per image needing size-only
    detection (its group's file-name sizes)."""
    ids = list(file_ids)
    if not ids:
        return {}
    images = db.query(Image).filter(Image.source_file_id.in_(ids)).all()
    targets: dict[int, RefreshTarget] = {}
    for image in images:
        siblings = (
            group_sibling_counts(db, image.id, image.group_id)
            if detection_mode(image, force=True) == "size"
            else ()
        )
        targets[image.source_file_id] = RefreshTarget.of(image, siblings)  # pyright: ignore[reportArgumentType]
    return targets


def _cleared(mode: DetectionMode) -> GridColumns:
    """Detection gave nothing for the new pixels: drop what was detected from the old
    ones, as a fresh import would have nothing. Size only keeps the file name's
    "gridded"."""
    if mode == "size":
        return {"grid_width": None, "grid_height": None, "grid_confidence": None}
    return {
        "gridded": None,
        "grid_width": None,
        "grid_height": None,
        "grid_type": None,
        "grid_confidence": None,
        "grid_source": None,
    }


def refresh_grid(
    target: RefreshTarget, path: Path, width: int, height: int, cfg: PipelineConfig
) -> GridColumns:
    """The grid columns to write for the edited file; empty keeps the image's grid.

    The re-detection rules are the forced backfill's (``grid_rules.detection_mode``):
    user grids and explicit file-name labels are kept (a name's NxM is re-oriented if
    the image turned), detected grids are detected again, and a file name that says
    gridded gets its size detected again.
    """
    mode = detection_mode(target, force=True)
    if mode is None:
        if target.grid_source == GRID_SOURCE_FILENAME and target.grid_width and target.grid_height:
            oriented = orient_grid(target.grid_width, target.grid_height, width, height)
            if oriented != (target.grid_width, target.grid_height):
                return {"grid_width": oriented[0], "grid_height": oriented[1]}
        return {}
    if not cfg.enable_image_grid_detection:
        return _cleared(mode)
    size_only = mode == "size"
    result = grid_detection.detect_grid_from_image(
        str(path),
        width,
        height,
        size_only=size_only,
        pipeline_config=cfg,
        sibling_counts=target.sibling_counts if size_only else (),
    )
    if not result or result.get("confidence", 0) <= 0:
        return _cleared(mode)
    if size_only:
        if result.get("grid_width") is None:
            return _cleared(mode)
        return {
            "grid_width": result["grid_width"],
            "grid_height": result["grid_height"],
            "grid_type": result.get("grid_type"),
            "grid_confidence": result.get("confidence"),
        }
    return {
        "gridded": result.get("gridded"),
        "grid_width": result.get("grid_width"),
        "grid_height": result.get("grid_height"),
        "grid_type": result.get("grid_type"),
        "grid_confidence": result.get("confidence"),
        "grid_source": GRID_SOURCE_DETECTOR,
    }
