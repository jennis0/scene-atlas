"""Grid detection for battlemaps (v3). See ``design/grid-detection-v3.md``."""

from .detector import SMALL_IMAGE_PX, detect_grid
from .models import GridModelError

__all__ = ["SMALL_IMAGE_PX", "GridModelError", "detect_grid"]
