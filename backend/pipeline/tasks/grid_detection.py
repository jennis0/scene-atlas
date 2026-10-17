"""Grid detection task — image-based grid analysis for battlemaps."""

from __future__ import annotations

import logging
from pathlib import Path

from backend.app.services.grid_detector import GridDetector
from backend.pipeline.pipeline_config import PipelineConfig


def detect_grid_from_image(
    image_path: str,
    width: int,
    height: int,
    size_only: bool = False,
    pipeline_config: PipelineConfig | None = None,
) -> dict:
    """Detect grid presence, type and tile dimensions.

    With *size_only*, presence detection is skipped (a grid is assumed).
    Returns gridded, grid_type, grid_width, grid_height and confidence.
    """
    logger = logging.getLogger(__name__)

    try:
        cfg = pipeline_config or PipelineConfig()
        detector = GridDetector(
            min_cell_px=cfg.grid_min_cell_px,
            max_cell_px=cfg.grid_max_cell_px,
            max_dim=cfg.grid_detection_max_dim,
            presence_threshold=cfg.grid_presence_threshold,
            size_threshold=cfg.grid_size_threshold,
            period_ratio_threshold=cfg.grid_period_ratio_threshold,
            hex_rot_conf=cfg.grid_hex_rot_conf,
        )

        path = Path(image_path)

        if size_only:
            result = detector.detect_size_only(path, width, height)
        else:
            result = detector.detect(path, width, height)

        logger.debug(
            "Grid detection for %s: gridded=%s, type=%s, size=%sx%s, confidence=%s",
            path.name,
            result["gridded"],
            result["grid_type"],
            result["grid_width"],
            result["grid_height"],
            result["confidence"],
        )

        return dict(result)

    except Exception:
        logger.exception("Grid detection failed for %s", image_path)
        return {
            "gridded": None,
            "grid_type": None,
            "grid_width": None,
            "grid_height": None,
            "confidence": 0.0,
        }
