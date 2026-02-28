"""Grid detection task — image-based grid analysis for battlemaps."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from backend.app.services.grid_detector import GridDetector
from backend.pipeline.logger import get_logger

if TYPE_CHECKING:
    from backend.pipeline.pipeline_config import PipelineConfig


def detect_grid_from_image(
    image_path: str,
    width: int,
    height: int,
    size_only: bool = False,
    pipeline_config: PipelineConfig | None = None,
) -> dict:
    """Detect grid presence, type, and dimensions from an image.

    Args:
        image_path: Path to the image.
        width: Original image width in pixels.
        height: Original image height in pixels.
        size_only: If True, skip presence detection (assumes grid exists).
        pipeline_config: Optional pipeline config for detector thresholds.
            Falls back to module-level defaults when not provided.

    Returns:
        Dict with gridded, grid_type, grid_width, grid_height, confidence.
    """
    logger = get_logger(__name__)

    try:
        if pipeline_config is not None:
            detector = GridDetector(
                min_cell_px=pipeline_config.grid_min_cell_px,
                max_cell_px=pipeline_config.grid_max_cell_px,
                max_dim=pipeline_config.grid_detection_max_dim,
                presence_threshold=pipeline_config.grid_presence_threshold,
                size_threshold=pipeline_config.grid_size_threshold,
                period_ratio_threshold=pipeline_config.grid_period_ratio_threshold,
                hex_rot_conf=pipeline_config.grid_hex_rot_conf,
            )
        else:
            # Fallback: use PipelineConfig dataclass defaults
            from backend.pipeline.pipeline_config import PipelineConfig

            _defaults = PipelineConfig()
            detector = GridDetector(
                min_cell_px=_defaults.grid_min_cell_px,
                max_cell_px=_defaults.grid_max_cell_px,
                max_dim=_defaults.grid_detection_max_dim,
                presence_threshold=_defaults.grid_presence_threshold,
                size_threshold=_defaults.grid_size_threshold,
                period_ratio_threshold=_defaults.grid_period_ratio_threshold,
                hex_rot_conf=_defaults.grid_hex_rot_conf,
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

    except Exception as e:
        logger.error("Grid detection failed for %s: %s", image_path, e)
        return {
            "gridded": None,
            "grid_type": None,
            "grid_width": None,
            "grid_height": None,
            "confidence": 0.0,
        }
