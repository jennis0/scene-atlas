"""Image-based grid detection for battlemaps.

Detects square and hexagonal grids using a hybrid approach:
1. Preprocess: grayscale + Canny edge detection (isolates grid lines)
2. Compute row/column projections of the edge image
3. Find dominant periods via FFT-based autocorrelation
4. Classify grid type from period ratio (square vs hex)
5. Validate against image dimensions (constraint check)
"""

import logging
import math
from pathlib import Path
from typing import TypedDict

import cv2
import numpy as np
from scipy.signal import find_peaks, fftconvolve

logger = logging.getLogger(__name__)

# sqrt(3)/2 ≈ 0.866 — characteristic ratio for hex grids
_SQRT3_OVER_2 = math.sqrt(3) / 2
# Tolerance for hex ratio classification (±15%)
_HEX_RATIO_TOLERANCE = 0.15


class GridDetectionResult(TypedDict):
    gridded: bool | None
    grid_type: str | None  # "square" | "hex" | None
    grid_width: int | None  # tile count horizontal
    grid_height: int | None  # tile count vertical
    confidence: float  # 0.0–1.0


_NO_GRID: GridDetectionResult = {
    "gridded": None,
    "grid_type": None,
    "grid_width": None,
    "grid_height": None,
    "confidence": 0.0,
}


class GridDetector:
    """Detect grid presence, type (square/hex), and dimensions in battlemap images."""

    def __init__(
        self,
        min_cell_px: int = 32,
        max_cell_px: int = 256,
        max_dim: int = 1024,
        presence_threshold: float = 0.3,
        size_threshold: float = 0.15,
    ):
        self.min_cell_px = min_cell_px
        self.max_cell_px = max_cell_px
        self.max_dim = max_dim
        self.presence_threshold = presence_threshold
        self.size_threshold = size_threshold

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect(
        self, image_path: Path, width: int, height: int
    ) -> GridDetectionResult:
        """Detect grid presence, type, and tile dimensions.

        Use when no filename hint is available — detects both presence and size.

        Args:
            image_path: Path to the image file.
            width: Original image width in pixels.
            height: Original image height in pixels.

        Returns:
            GridDetectionResult with gridded, grid_type, grid_width, grid_height,
            and confidence.
        """
        return self._run(image_path, width, height, self.presence_threshold)

    def detect_size_only(
        self, image_path: Path, width: int, height: int
    ) -> GridDetectionResult:
        """Detect grid size when presence is already known (lower threshold).

        Use when the filename already indicates a grid is present.
        """
        result = self._run(image_path, width, height, self.size_threshold)
        # Since we know it's gridded, force gridded=True even at lower confidence
        if result["grid_width"] is not None:
            result["gridded"] = True
        return result

    # ------------------------------------------------------------------
    # Core pipeline
    # ------------------------------------------------------------------

    def _run(
        self,
        image_path: Path,
        orig_width: int,
        orig_height: int,
        threshold: float,
    ) -> GridDetectionResult:
        """Core detection pipeline."""
        edges, scale = self._preprocess(image_path)
        if edges is None:
            return {**_NO_GRID}

        scaled_h, scaled_w = edges.shape

        # Compute min/max cell sizes in the scaled image
        min_cell = max(4, int(self.min_cell_px * scale))
        max_cell = min(min(scaled_h, scaled_w) // 3, int(self.max_cell_px * scale))

        if min_cell >= max_cell:
            logger.debug("Image too small for grid detection after scaling")
            return {**_NO_GRID}

        # Row projection (average across columns → one value per row)
        row_proj = self._compute_projection(edges, axis=1)
        # Column projection (average across rows → one value per column)
        col_proj = self._compute_projection(edges, axis=0)

        # Find dominant periods
        v_period, v_strength = self._find_dominant_period(row_proj, min_cell, max_cell)
        h_period, h_strength = self._find_dominant_period(col_proj, min_cell, max_cell)

        logger.debug(
            f"Detected periods: h={h_period}px (strength={h_strength:.3f}), "
            f"v={v_period}px (strength={v_strength:.3f}), scale={scale:.3f}"
        )

        # Both periods must have some signal
        if h_period is None and v_period is None:
            return {**_NO_GRID}

        # Classify grid type from period ratio
        grid_type = self._classify_grid_type(
            h_period, v_period, h_strength, v_strength
        )

        # Compute confidence as the geometric mean of the two strengths
        if h_strength > 0 and v_strength > 0:
            confidence = math.sqrt(h_strength * v_strength)
        else:
            confidence = max(h_strength, v_strength) * 0.5

        if confidence < threshold:
            return {**_NO_GRID, "confidence": confidence}

        # Convert periods back to original pixel scale
        if h_period is not None:
            h_period_orig = h_period / scale
        else:
            h_period_orig = None
        if v_period is not None:
            v_period_orig = v_period / scale
        else:
            v_period_orig = None

        # Snap to integer divisors of image dimensions → tile counts
        grid_width = None
        grid_height = None

        if grid_type == "hex":
            grid_width, grid_height = self._compute_hex_tile_counts(
                h_period_orig, v_period_orig, orig_width, orig_height
            )
        else:
            # Square grid: both periods should be similar
            if h_period_orig is not None:
                grid_width = self._snap_to_tile_count(h_period_orig, orig_width)
            if v_period_orig is not None:
                grid_height = self._snap_to_tile_count(v_period_orig, orig_height)

        gridded = True if confidence >= threshold else None

        return {
            "gridded": gridded,
            "grid_type": grid_type,
            "grid_width": grid_width,
            "grid_height": grid_height,
            "confidence": round(confidence, 3),
        }

    # ------------------------------------------------------------------
    # Preprocessing
    # ------------------------------------------------------------------

    def _preprocess(self, image_path: Path) -> tuple[np.ndarray | None, float]:
        """Load image, convert to grayscale, downsample, and apply Canny edge detection.

        Returns:
            (edge_image, scale_factor) where scale_factor maps scaled px → original px.
            Returns (None, 0) if image cannot be loaded.
        """
        img = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
        if img is None:
            logger.warning(f"Could not read image: {image_path}")
            return None, 0.0

        h, w = img.shape
        scale = 1.0

        if max(h, w) > self.max_dim:
            scale = self.max_dim / max(h, w)
            new_w = max(1, int(w * scale))
            new_h = max(1, int(h * scale))
            img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)

        # Canny edge detection — tuned for grid lines
        # Use adaptive thresholds based on image statistics
        median_val = np.median(img)
        lower = int(max(0, 0.5 * median_val))
        upper = int(min(255, 1.5 * median_val))
        edges = cv2.Canny(img, lower, upper)

        return edges, scale

    # ------------------------------------------------------------------
    # Projection + autocorrelation
    # ------------------------------------------------------------------

    def _compute_projection(self, edges: np.ndarray, axis: int) -> np.ndarray:
        """Compute mean intensity projection along the given axis.

        axis=0: mean across rows → column projection (one value per column)
        axis=1: mean across columns → row projection (one value per row)
        """
        projection = np.mean(edges.astype(np.float64), axis=axis)
        return projection

    def _find_dominant_period(
        self,
        projection: np.ndarray,
        min_period: int,
        max_period: int,
    ) -> tuple[int | None, float]:
        """Find the dominant periodic spacing in a projection using FFT-based autocorrelation.

        Returns:
            (period_in_scaled_pixels, peak_strength) where strength is 0.0–1.0.
            Returns (None, 0.0) if no clear period is found.
        """
        n = len(projection)
        if n < min_period * 2:
            return None, 0.0

        # Zero-mean the projection
        projection = projection - np.mean(projection)

        # Guard against zero-variance signals
        std = np.std(projection)
        if std < 1e-10:
            return None, 0.0

        # Normalize
        projection = projection / std

        # FFT-based autocorrelation: autocorr = IFFT(|FFT(x)|^2)
        # Use fftconvolve(x, x[::-1]) which is equivalent and handles padding
        autocorr = fftconvolve(projection, projection[::-1], mode="full")
        # Take the right half (positive lags)
        autocorr = autocorr[n - 1 :]
        # Normalize by zero-lag (which equals the signal energy)
        zero_lag = autocorr[0]
        if zero_lag < 1e-10:
            return None, 0.0
        autocorr = autocorr / zero_lag

        # Search for peaks only within our cell size range
        search_start = min_period
        search_end = min(max_period + 1, len(autocorr))

        if search_start >= search_end:
            return None, 0.0

        search_region = autocorr[search_start:search_end]

        # Find peaks with minimum prominence to filter noise
        peaks, properties = find_peaks(
            search_region,
            prominence=0.05,
            distance=max(1, min_period // 2),
        )

        if len(peaks) == 0:
            return None, 0.0

        # Pick the peak with the highest prominence
        best_idx = peaks[np.argmax(properties["prominences"])]
        period = best_idx + search_start
        strength = float(autocorr[period])

        # Strength should be positive for a real periodic signal
        if strength <= 0:
            return None, 0.0

        return int(period), min(1.0, strength)

    # ------------------------------------------------------------------
    # Grid type classification
    # ------------------------------------------------------------------

    def _classify_grid_type(
        self,
        h_period: int | None,
        v_period: int | None,
        h_strength: float,
        v_strength: float,
    ) -> str | None:
        """Classify as 'square', 'hex', or None based on the ratio of detected periods.

        Square grids have ratio ≈ 1.0.
        Hex grids have ratio ≈ sqrt(3)/2 ≈ 0.866 or its inverse ≈ 1.155.
        """
        if h_period is None or v_period is None:
            # Only one axis has periodicity — can't classify reliably
            if h_period is not None or v_period is not None:
                return "square"  # Best guess with one axis
            return None

        if h_period == 0 or v_period == 0:
            return None

        ratio = min(h_period, v_period) / max(h_period, v_period)

        # Check square first (more common): ratio ≈ 1.0 (within 10%)
        if ratio > 0.90:
            return "square"

        # Check for hex: ratio ≈ sqrt(3)/2 ≈ 0.866 (within ±10%)
        if abs(ratio - _SQRT3_OVER_2) < 0.10:
            return "hex"

        # Ambiguous ratio — default to square if both signals are strong
        if h_strength > 0.2 and v_strength > 0.2:
            return "square"

        return None

    # ------------------------------------------------------------------
    # Tile count computation
    # ------------------------------------------------------------------

    def _snap_to_tile_count(
        self,
        period_px: float,
        image_dim: int,
        tolerance: float = 0.10,
    ) -> int | None:
        """Convert a detected period (in pixels) to a tile count along an image dimension.

        Looks for the nearest integer tile count where the implied cell size
        is close to the detected period.

        Returns:
            Tile count (int), or None if no good fit.
        """
        if period_px <= 0 or image_dim <= 0:
            return None

        # Expected tile count (may be fractional)
        expected_tiles = image_dim / period_px

        # Try rounding to nearest integer
        for candidate in [round(expected_tiles), int(expected_tiles), int(expected_tiles) + 1]:
            if candidate <= 0:
                continue
            actual_cell_size = image_dim / candidate
            relative_error = abs(actual_cell_size - period_px) / period_px
            if relative_error < tolerance:
                return candidate

        return round(expected_tiles) if expected_tiles >= 1 else None

    def _compute_hex_tile_counts(
        self,
        h_period_px: float | None,
        v_period_px: float | None,
        orig_width: int,
        orig_height: int,
    ) -> tuple[int | None, int | None]:
        """Compute hex grid tile counts from detected periods.

        For hex grids, the relationship between tile counts and image dimensions
        depends on the hex orientation. We use the longer period to determine
        orientation and compute both counts.

        Returns:
            (grid_width, grid_height) as tile counts.
        """
        if h_period_px is None and v_period_px is None:
            return None, None

        grid_width = None
        grid_height = None

        if h_period_px is not None:
            grid_width = self._snap_to_tile_count(h_period_px, orig_width, tolerance=0.15)
        if v_period_px is not None:
            grid_height = self._snap_to_tile_count(v_period_px, orig_height, tolerance=0.15)

        return grid_width, grid_height
