"""Grid detection entry point: v3 for normal maps, the legacy detector for small ones.

Images whose longest side is under ``SMALL_IMAGE_PX`` go to the legacy detector: on
small maps (few pixels per cell, few cells) v3 was measurably worse in cross-artist
evaluation (``design/grid-detection-v3.md`` §4, rounds 4-5).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path

from ..grid_detector import GridDetectionResult, GridDetector
from .analysis import AnalysisParams
from .features import feature_vector, measure
from .models import GridModels, get_models

logger = logging.getLogger(__name__)

SMALL_IMAGE_PX = 1000

# A square grid has lines on both axes, so presence also needs some line contrast on the
# weaker axis. On out-of-fold predictions for 2,080 twin images this cut lost no true
# grid and removed 3 of 46 false positives; the 0.5th percentile of real grids is 1.23.
# It does not catch every one-directional pattern (perfectly regular planks can still
# pass): the model never saw such patterns in training (design/grid-detection-v3.md §6).
MIN_WEAKER_AXIS_CONTRAST = 1.15

_UNKNOWN: GridDetectionResult = {
    "gridded": None,
    "grid_type": None,
    "grid_width": None,
    "grid_height": None,
    "confidence": 0.0,
}


def detect_grid(
    path: Path,
    width: int,
    height: int,
    *,
    size_only: bool = False,
    sibling_counts: Sequence[tuple[int, int]] = (),
    max_analysis_dim: int | None = None,
) -> GridDetectionResult:
    """Detect whether a battlemap has a drawn grid, its type, and its tile counts.

    Args:
        path: The image file.
        width, height: Its size in pixels (from the header).
        size_only: The filename already says gridded; only the tile counts are wanted.
        sibling_counts: Tile counts read from other files' names in the same group.
            Used as candidates in size-only mode, never as truth.
        max_analysis_dim: Analyse at full resolution when None; otherwise reduce images
            larger than this. Lower values are faster but miss thin lines on high-dpi maps.

    Returns ``gridded=None`` when the image can't be read. Raises ``GridModelError`` if
    the bundled models are missing or don't match the code (a system problem, not a
    property of this file).
    """
    if max(width, height) < SMALL_IMAGE_PX:
        legacy = GridDetector()
        if size_only:
            return legacy.detect_size_only(path, width, height)
        return legacy.detect(path, width, height)

    models = get_models()
    m = measure(
        path,
        width,
        height,
        AnalysisParams(max_analysis_dim=max_analysis_dim),
        sibling_counts=sibling_counts if size_only else (),
    )
    if m is None:
        logger.warning("Grid detection could not read %s", path.name)
        return dict(_UNKNOWN)  # type: ignore[return-value]
    return classify(m, models, size_only=size_only)


def classify(m: dict, models: GridModels, *, size_only: bool = False) -> GridDetectionResult:
    """Turn measurements into a result: hex first, then square presence and counts."""
    hex_p = models.hex_probability(feature_vector(m, models.hex_features))
    presence_p = (
        models.presence_probability(feature_vector(m, models.presence_features))
        if m.get("ok")
        else 0.0
    )
    if hex_p >= models.threshold:
        return {
            "gridded": True,
            "grid_type": "hex",
            "grid_width": None,
            "grid_height": None,
            "confidence": round(hex_p, 3),
        }
    counts = tile_counts(m, models.sibling_prior_beta if size_only else None)
    if size_only:
        return {
            "gridded": True,
            "grid_type": "square" if counts else None,
            "grid_width": counts[0] if counts else None,
            "grid_height": counts[1] if counts else None,
            "confidence": round(presence_p, 3),
        }
    weaker_axis = min(m.get("contrast_x") or 0.0, m.get("contrast_y") or 0.0)
    if presence_p >= models.threshold and counts and weaker_axis >= MIN_WEAKER_AXIS_CONTRAST:
        return {
            "gridded": True,
            "grid_type": "square",
            "grid_width": counts[0],
            "grid_height": counts[1],
            "confidence": round(presence_p, 3),
        }
    return {
        "gridded": False,
        "grid_type": None,
        "grid_width": None,
        "grid_height": None,
        "confidence": round(presence_p, 3),
    }


def tile_counts(m: dict, sibling_beta: float | None = None) -> tuple[int, int] | None:
    """The comb's own counts, or the best sibling candidate when it scores at least
    ``sibling_beta`` x the comb's own pick (size-only prior)."""
    if not m.get("ok") or m.get("nx") is None:
        return None
    own = (int(round(m["nx"])), int(round(m["ny"])))
    candidates = m.get("sibling_scores") or {}
    if sibling_beta is None or not candidates:
        return own
    best, best_score = max(candidates.items(), key=lambda kv: kv[1])
    return tuple(best) if best_score >= sibling_beta * m["own_score"] else own
