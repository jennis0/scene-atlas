"""Color proximity search using HSL cylindrical distance with in-memory caching."""

import colorsys
import math
import time
from typing import Optional

from sqlalchemy.orm import Session

from ..config import settings
from ..models import Color

# Cache TTL in seconds
_CACHE_TTL = 60.0


def hex_to_hsl_cylinder(hex_color: str) -> tuple[float, float, float]:
    """Convert a hex color to cylindrical HSL coordinates.

    Maps HSL to a 3D point where Euclidean distance is perceptually reasonable:
      x = S * cos(H * 2pi)
      y = S * sin(H * 2pi)
      z = L

    This handles hue wraparound naturally and clusters grays together.
    """
    h_str = hex_color.lstrip("#")
    r, g, b = int(h_str[0:2], 16) / 255, int(h_str[2:4], 16) / 255, int(h_str[4:6], 16) / 255
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    angle = h * 2 * math.pi
    x = s * math.cos(angle)
    y = s * math.sin(angle)
    return (x, y, l)


def color_distance(v1: tuple[float, float, float], v2: tuple[float, float, float]) -> float:
    """Euclidean distance between two cylindrical HSL vectors."""
    return math.sqrt((v1[0] - v2[0]) ** 2 + (v1[1] - v2[1]) ** 2 + (v1[2] - v2[2]) ** 2)


class ColorIndex:
    """In-memory index of image colors for fast proximity search.

    Loads all (image_id, color_hex) pairs from the database, pre-converts
    to cylindrical HSL, and caches for repeated queries. Refreshes lazily
    when the cache TTL expires.
    """

    def __init__(self):
        self._cache: list[tuple[int, tuple[float, float, float]]] = []
        self._loaded_at: float = 0.0

    def _refresh(self, db: Session) -> None:
        """Reload color data from the database."""
        rows = db.query(Color.image_id, Color.color_hex).all()
        self._cache = [(image_id, hex_to_hsl_cylinder(hex_val)) for image_id, hex_val in rows]
        self._loaded_at = time.monotonic()

    def _ensure_loaded(self, db: Session) -> None:
        if not self._cache or (time.monotonic() - self._loaded_at) > _CACHE_TTL:
            self._refresh(db)

    def find_images_by_color(
        self,
        db: Session,
        target_hex: str,
        threshold: Optional[float] = None,
    ) -> set[int]:
        """Find image IDs with at least one dominant color within threshold of target."""
        self._ensure_loaded(db)
        if threshold is None:
            threshold = settings.color_distance_threshold

        target = hex_to_hsl_cylinder(target_hex)
        return {
            image_id
            for image_id, vec in self._cache
            if color_distance(target, vec) <= threshold
        }

    def find_images_by_colors(
        self,
        db: Session,
        target_hexes: list[str],
        threshold: Optional[float] = None,
    ) -> set[int]:
        """Find image IDs matching ANY of the target colors (OR logic)."""
        result: set[int] = set()
        for hex_val in target_hexes:
            result |= self.find_images_by_color(db, hex_val, threshold)
        return result


# Global instance
color_index = ColorIndex()
