"""Grid detection Prefect task — image-based grid analysis for battlemaps."""

from pathlib import Path

from prefect import task

from backend.app.config import settings
from backend.app.services.grid_detector import GridDetector
from backend.flows.logger import get_logger


@task(name="detect_grid_from_image", retries=1)
def detect_grid_from_image(
    image_path: str,
    width: int,
    height: int,
    size_only: bool = False,
) -> dict:
    """Detect grid presence, type, and dimensions from an image.

    Args:
        image_path: Path to the image (as string for Prefect serialization).
        width: Original image width in pixels.
        height: Original image height in pixels.
        size_only: If True, skip presence detection (assumes grid exists).

    Returns:
        Dict with gridded, grid_type, grid_width, grid_height, confidence.
    """
    logger = get_logger(__name__)

    try:
        detector = GridDetector(
            min_cell_px=settings.grid_min_cell_px,
            max_cell_px=settings.grid_max_cell_px,
            max_dim=settings.grid_detection_max_dim,
            presence_threshold=settings.grid_presence_threshold,
            size_threshold=settings.grid_size_threshold,
        )

        path = Path(image_path)

        if size_only:
            result = detector.detect_size_only(path, width, height)
        else:
            result = detector.detect(path, width, height)

        logger.debug(
            f"Grid detection for {path.name}: "
            f"gridded={result['gridded']}, type={result['grid_type']}, "
            f"size={result['grid_width']}x{result['grid_height']}, "
            f"confidence={result['confidence']:.3f}"
        )

        return dict(result)

    except Exception as e:
        logger.error(f"Grid detection failed for {image_path}: {e}")
        return {
            "gridded": None,
            "grid_type": None,
            "grid_width": None,
            "grid_height": None,
            "confidence": 0.0,
        }
