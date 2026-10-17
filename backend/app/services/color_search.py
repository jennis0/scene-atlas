"""Color proximity search using HSL cylindrical distance with in-memory caching."""

import colorsys
import math
import threading
import time

import numpy as np
from sqlalchemy.orm import Session

from backend.app.config import settings as _settings

from ..models import Color


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
    h, lightness, s = colorsys.rgb_to_hls(r, g, b)
    angle = h * 2 * math.pi
    x = s * math.cos(angle)
    y = s * math.sin(angle)
    return (x, y, lightness)


def color_distance(v1: tuple[float, float, float], v2: tuple[float, float, float]) -> float:
    """Euclidean distance between two cylindrical HSL vectors."""
    return math.sqrt((v1[0] - v2[0]) ** 2 + (v1[1] - v2[1]) ** 2 + (v1[2] - v2[2]) ** 2)


_REFRESH_CHUNK = 20_000


def _hsl_cylinders(hexes: list[str]) -> np.ndarray:
    """Vectorised ``hex_to_hsl_cylinder`` (same formulas as ``colorsys.rgb_to_hls``)."""
    packed = np.fromiter((int(h.lstrip("#")[:6], 16) for h in hexes), np.int64, len(hexes))
    r = ((packed >> 16) & 0xFF) / 255.0
    g = ((packed >> 8) & 0xFF) / 255.0
    b = (packed & 0xFF) / 255.0
    maxc = np.maximum(np.maximum(r, g), b)
    minc = np.minimum(np.minimum(r, g), b)
    span = maxc - minc
    lightness = (maxc + minc) / 2.0
    chromatic = span > 0
    safe_span = np.where(chromatic, span, 1.0)
    saturation = np.where(
        lightness <= 0.5,
        span / np.where(chromatic, maxc + minc, 1.0),
        span / np.where(chromatic, 2.0 - maxc - minc, 1.0),
    )
    saturation = np.where(chromatic, saturation, 0.0)
    rc, gc, bc = (maxc - r) / safe_span, (maxc - g) / safe_span, (maxc - b) / safe_span
    hue = np.where(r == maxc, bc - gc, np.where(g == maxc, 2.0 + rc - bc, 4.0 + gc - rc))
    hue = np.where(chromatic, (hue / 6.0) % 1.0, 0.0)
    angle = hue * 2 * math.pi
    return np.column_stack((saturation * np.cos(angle), saturation * np.sin(angle), lightness))


class ColorIndex:
    """In-memory index of image colours for proximity search.

    Holds every (image_id, colour) pair as numpy arrays: about 16 bytes per
    colour, so ~5 MB for a 56k-image library at 5 colours each (a list of
    Python tuples took ~65 MB). Searches are a vectorised distance over the
    arrays. Refreshes lazily when the cache TTL expires.
    """

    def __init__(self):
        self._ids = np.empty(0, dtype=np.int64)
        self._vectors = np.empty((0, 3), dtype=np.float64)
        self._loaded_at: float | None = None
        self._lock = threading.Lock()

    def invalidate(self) -> None:
        """Reload on next use (e.g. after the colours table changed wholesale)."""
        with self._lock:
            self._loaded_at = None

    def _refresh(self, db: Session) -> None:
        """Reload colour data from the database, streaming rows in chunks."""
        id_chunks: list[np.ndarray] = []
        vector_chunks: list[np.ndarray] = []
        image_ids: list[int] = []
        hexes: list[str] = []
        for image_id, hex_val in db.query(Color.image_id, Color.color_hex).yield_per(
            _REFRESH_CHUNK
        ):
            image_ids.append(image_id)
            hexes.append(hex_val)
            if len(hexes) >= _REFRESH_CHUNK:
                id_chunks.append(np.asarray(image_ids, dtype=np.int64))
                vector_chunks.append(_hsl_cylinders(hexes))
                image_ids, hexes = [], []
        if hexes:
            id_chunks.append(np.asarray(image_ids, dtype=np.int64))
            vector_chunks.append(_hsl_cylinders(hexes))
        ids = np.concatenate(id_chunks) if id_chunks else np.empty(0, dtype=np.int64)
        vectors = np.concatenate(vector_chunks) if vector_chunks else np.empty((0, 3))
        with self._lock:
            self._ids, self._vectors = ids, vectors
            self._loaded_at = time.monotonic()

    def _ensure_loaded(self, db: Session) -> tuple[np.ndarray, np.ndarray]:
        with self._lock:
            loaded_at = self._loaded_at
            if (
                loaded_at is not None
                and time.monotonic() - loaded_at <= _settings.color_cache_ttl_seconds
            ):
                return self._ids, self._vectors
        self._refresh(db)
        with self._lock:
            return self._ids, self._vectors

    def find_images_by_color(
        self,
        db: Session,
        target_hex: str,
        threshold: float | None = None,
    ) -> set[int]:
        """Find image IDs with at least one dominant color within threshold of target."""
        return self.find_images_by_colors(db, [target_hex], threshold)

    def find_images_by_colors(
        self,
        db: Session,
        target_hexes: list[str],
        threshold: float | None = None,
    ) -> set[int]:
        """Find image IDs matching ANY of the target colors (OR logic)."""
        ids, vectors = self._ensure_loaded(db)
        if threshold is None:
            from .app_settings import get_settings as get_app_settings

            threshold = get_app_settings(db).color_distance_threshold
        matched = np.zeros(len(ids), dtype=bool)
        for hex_val in target_hexes:
            target = np.asarray(hex_to_hsl_cylinder(hex_val))
            matched |= np.sqrt(((vectors - target) ** 2).sum(axis=1)) <= threshold
        return set(ids[matched].tolist())


# Global instance
color_index = ColorIndex()
