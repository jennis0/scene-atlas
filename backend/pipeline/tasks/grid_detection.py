"""Grid detection task: image-based grid analysis for battlemaps (v3)."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path

from backend.app.services.grid import GridModelError, detect_grid
from backend.pipeline.pipeline_config import PipelineConfig

logger = logging.getLogger(__name__)

_UNKNOWN = {
    "gridded": None,
    "grid_type": None,
    "grid_width": None,
    "grid_height": None,
    "confidence": 0.0,
}


def detect_grid_from_image(
    image_path: str,
    width: int,
    height: int,
    size_only: bool = False,
    pipeline_config: PipelineConfig | None = None,
    sibling_counts: Sequence[tuple[int, int]] = (),
) -> dict:
    """Detect grid presence, type and tile counts from an image.

    Args:
        image_path: Path to the image.
        width, height: Original image size in pixels.
        size_only: The filename already says gridded; only the tile counts are wanted.
        pipeline_config: Source of ``grid_analysis_max_dim``; defaults when omitted.
        sibling_counts: NxM grid sizes named by other files in the same group
            (candidates for size-only mode).

    Returns a dict with gridded, grid_type, grid_width, grid_height and confidence.
    An unexpected analysis error is logged and reported as "unknown"; it says nothing
    about the image being bad. Missing or mismatched models raise ``GridModelError``,
    which callers must treat as a system problem.
    """
    cfg = pipeline_config or PipelineConfig()
    path = Path(image_path)
    try:
        result = detect_grid(
            path,
            width,
            height,
            size_only=size_only,
            sibling_counts=sibling_counts,
            max_analysis_dim=cfg.grid_max_dim,
        )
    except GridModelError:
        raise
    except Exception:
        logger.exception("Grid detection failed for %s", path.name)
        return dict(_UNKNOWN)
    logger.debug(
        "Grid detection for %s: gridded=%s type=%s size=%sx%s confidence=%s",
        path.name,
        result["gridded"],
        result["grid_type"],
        result["grid_width"],
        result["grid_height"],
        result["confidence"],
    )
    return dict(result)
