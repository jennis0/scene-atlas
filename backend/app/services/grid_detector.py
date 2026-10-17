"""Image-based grid detection for battlemaps.

Detects square and hex grids using paired-peak autocorrelation:
1. Preprocess: grayscale + Canny edge detection (isolates grid lines)
2. Standard orientation: row/column projections + AC peak finding
3. 30-degree rotation: aligns hex grid lines with axes for hex detection
4. Classification: hex if rotation signal is strong, square if standard
   signal is strong with ~1.0 period ratio, else no grid
5. Tile count estimation for square grids via period snapping
"""

import logging
import math
from pathlib import Path
from typing import TypedDict

import cv2
import numpy as np
from scipy.signal import fftconvolve, find_peaks

logger = logging.getLogger(__name__)

# Decoder-side downscaling flags, largest reduction first.
_REDUCED_GRAYSCALE = (
    (8, cv2.IMREAD_REDUCED_GRAYSCALE_8),
    (4, cv2.IMREAD_REDUCED_GRAYSCALE_4),
    (2, cv2.IMREAD_REDUCED_GRAYSCALE_2),
)


class GridDetectionResult(TypedDict):
    gridded: bool | None
    grid_type: str | None  # "square" | "hex" | None
    grid_width: int | None  # tile count horizontal (square only)
    grid_height: int | None  # tile count vertical (square only)
    confidence: float  # 0.0-1.0


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
        max_cell_px: int = 320,
        max_dim: int = 8_000,
        presence_threshold: float = 0.20,
        size_threshold: float = 0.15,
        period_ratio_threshold: float = 0.98,
        hex_rot_conf: float = 0.20,
    ):
        self.min_cell_px = min_cell_px
        self.max_cell_px = max_cell_px
        self.max_dim = max_dim
        self.presence_threshold = presence_threshold
        self.size_threshold = size_threshold
        self.period_ratio_threshold = period_ratio_threshold
        self.hex_rot_conf = hex_rot_conf

    # Public API

    def detect(self, image_path: Path, width: int, height: int) -> GridDetectionResult:
        """Detect grid presence, type, and tile dimensions from pixels alone.

        Use when no filename hint is available. ``width``/``height`` are the
        original image dimensions, used to convert periods into tile counts.
        """
        return self._run(image_path, width, height, self.presence_threshold)

    def detect_size_only(self, image_path: Path, width: int, height: int) -> GridDetectionResult:
        """Detect grid size when presence is already known (lower threshold).

        Use when the filename already indicates a grid is present.
        """
        result = self._run(image_path, width, height, self.size_threshold)
        # Since we know it's gridded, force gridded=True even at lower confidence
        if result["grid_width"] is not None or result["grid_type"] is not None:
            result["gridded"] = True
        return result

    # Core pipeline

    def _run(
        self,
        image_path: Path,
        orig_width: int,
        orig_height: int,
        threshold: float,
    ) -> GridDetectionResult:
        """Core detection pipeline: standard AC + 30-degree rotation for hex."""
        edges, scale = self._preprocess(image_path, orig_width, orig_height)
        if edges is None:
            return {**_NO_GRID}

        min_cell = max(4, int(self.min_cell_px * scale))
        max_cell = min(
            min(edges.shape[0], edges.shape[1]) // 3,
            int(self.max_cell_px * scale),
        )

        if min_cell >= max_cell:
            logger.debug("Image too small for grid detection after scaling")
            return {
                "gridded": False,
                "grid_type": None,
                "grid_width": None,
                "grid_height": None,
                "confidence": 0.0,
            }

        # Standard orientation
        std = self._run_ac_on_edges(edges, min_cell, max_cell)

        # 30-degree rotation (hex detection)
        rot_edges = self._rotate_edges(edges, 30)
        rot_h, rot_w = rot_edges.shape
        min_cell_r = max(4, int(self.min_cell_px * scale))
        max_cell_r = min(min(rot_h, rot_w) // 3, int(self.max_cell_px * scale))
        if min_cell_r < max_cell_r:
            rot = self._run_ac_on_edges(rot_edges, min_cell_r, max_cell_r)
        else:
            rot = {
                "confidence": 0.0,
                "ratio": 0.0,
                "h_period": None,
                "v_period": None,
                "h_strength": 0.0,
                "v_strength": 0.0,
            }

        max_conf = max(std["confidence"], rot["confidence"])

        logger.debug(
            "Standard: conf=%s ratio=%s, Rotated: conf=%s, scale=%s",
            std["confidence"],
            std["ratio"],
            rot["confidence"],
            scale,
        )

        # Classification
        # Note: _NO_GRID has gridded=None (truly unknown / couldn't analyze).
        # When we HAVE analyzed and concluded no grid, we return gridded=False.

        # 1. No grid if overall confidence too low
        if max_conf < threshold:
            return {
                "gridded": False,
                "grid_type": None,
                "grid_width": None,
                "grid_height": None,
                "confidence": max_conf,
            }

        # 2. Hex: rotation signal is the key discriminator
        #    (30deg rotation aligns one set of hex lines with the vertical axis,
        #     producing strong AC signal; square grids lose signal at 30deg)
        if rot["confidence"] >= self.hex_rot_conf:
            return {
                "gridded": True,
                "grid_type": "hex",
                "grid_width": None,
                "grid_height": None,
                "confidence": round(max_conf, 3),
            }

        # 3. Square: strong standard signal with period ratio ~1.0
        if std["confidence"] >= threshold and std["ratio"] >= self.period_ratio_threshold:
            return self._build_square_result(std, scale, orig_width, orig_height)

        # 4. No grid (above threshold but didn't match square or hex pattern)
        return {
            "gridded": False,
            "grid_type": None,
            "grid_width": None,
            "grid_height": None,
            "confidence": max_conf,
        }

    def _run_ac_on_edges(
        self,
        edges: np.ndarray,
        min_cell: int,
        max_cell: int,
    ) -> dict:
        """Run 1D autocorrelation on an edge image.

        Returns dict with h_period, v_period, h_strength, v_strength,
        confidence, and ratio.
        """
        row_proj = np.asarray(np.mean(edges, axis=1, dtype=np.float64))
        col_proj = np.asarray(np.mean(edges, axis=0, dtype=np.float64))

        v_candidates, _ = self._find_ac_peaks(row_proj, min_cell, max_cell)
        h_candidates, _ = self._find_ac_peaks(col_proj, min_cell, max_cell)

        hp, hs, vp, vs = self._pick_best_periods(h_candidates, v_candidates)

        if hs > 0 and vs > 0:
            confidence = math.sqrt(hs * vs)
        else:
            confidence = max(hs, vs) * 0.5

        ratio = min(hp, vp) / max(hp, vp) if hp and vp else 0.0

        return {
            "h_period": hp,
            "v_period": vp,
            "h_strength": hs,
            "v_strength": vs,
            "confidence": confidence,
            "ratio": ratio,
        }

    def _build_square_result(
        self,
        std: dict,
        scale: float,
        orig_width: int,
        orig_height: int,
    ) -> GridDetectionResult:
        """Build result for a detected square grid with tile counts."""
        hp = std["h_period"]
        vp = std["v_period"]

        h_period_orig = hp / scale if hp is not None else None
        v_period_orig = vp / scale if vp is not None else None

        grid_width = None
        grid_height = None

        # Use vertical period as anchor (empirically more reliable)
        if v_period_orig is not None:
            grid_height = self._snap_to_tile_count(v_period_orig, orig_height)
            grid_width = self._snap_to_tile_count(v_period_orig, orig_width)
        if grid_width is None and h_period_orig is not None:
            grid_width = self._snap_to_tile_count(h_period_orig, orig_width)

        return {
            "gridded": True,
            "grid_type": "square",
            "grid_width": grid_width,
            "grid_height": grid_height,
            "confidence": round(std["confidence"], 3),
        }

    # Preprocessing

    def _read_gray(self, image_path: Path, longest_side: int) -> np.ndarray | None:
        """Read as grayscale, letting the decoder downscale when the cap allows.

        For JPEGs, the IMREAD_REDUCED_* flags decode directly at 1/2, 1/4 or 1/8
        scale (libjpeg DCT scaling), so a 760 Mpx map never materialises at full
        resolution. The largest factor that keeps the result at or above
        ``max_dim`` is used; the final resize to ``max_dim`` happens afterwards.
        """
        flag = cv2.IMREAD_GRAYSCALE
        for factor, reduced in _REDUCED_GRAYSCALE:
            if longest_side / factor >= self.max_dim:
                flag = reduced
                break
        return cv2.imread(str(image_path), flag)

    def _preprocess(
        self, image_path: Path, orig_width: int = 0, orig_height: int = 0
    ) -> tuple[np.ndarray | None, float]:
        """Load image, convert to grayscale, optionally downsample, and apply Canny.

        Returns:
            (edge_image, scale_factor) where scale_factor maps scaled px → original px.
            Returns (None, 0) if image cannot be loaded.
        """
        longest = max(orig_width, orig_height)
        img = self._read_gray(image_path, longest)
        if img is None:
            logger.warning("Could not read image: %s", image_path)
            return None, 0.0

        h, w = img.shape
        if not longest:  # original size unknown: what we read is full size
            orig_width, orig_height, longest = w, h, max(h, w)

        scale = 1.0
        if longest > self.max_dim:
            # Scale is relative to the original, not to the (possibly reduced) read.
            scale = self.max_dim / longest
            new_w = max(1, int(orig_width * scale))
            new_h = max(1, int(orig_height * scale))
            if (new_w, new_h) != (w, h):
                img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)

        # Canny edge detection with adaptive thresholds
        median_val = np.median(img)
        lower = int(max(0, 0.5 * median_val))
        upper = int(min(255, 1.5 * median_val))
        edges = cv2.Canny(img, lower, upper)

        return edges, scale

    # Rotation

    @staticmethod
    def _rotate_edges(edges: np.ndarray, angle_deg: float) -> np.ndarray:
        """Rotate an edge image by the given angle, expanding the canvas.

        Crops a 20% margin after rotation to remove sparse border regions
        introduced by the canvas expansion.
        """
        sh, sw = edges.shape
        M = cv2.getRotationMatrix2D((sw / 2, sh / 2), angle_deg, 1.0)
        cos_a, sin_a = abs(M[0, 0]), abs(M[0, 1])
        new_w = int(sh * sin_a + sw * cos_a)
        new_h = int(sh * cos_a + sw * sin_a)
        M[0, 2] += (new_w - sw) / 2
        M[1, 2] += (new_h - sh) / 2
        rotated = cv2.warpAffine(edges, M, (new_w, new_h))

        # Crop margins to avoid sparse border artefacts
        margin = int(min(new_h, new_w) * 0.20)
        if margin > 0 and new_h > 2 * margin and new_w > 2 * margin:
            rotated = rotated[margin:-margin, margin:-margin]

        return rotated

    # Autocorrelation peak finding

    def _find_ac_peaks(
        self,
        projection: np.ndarray,
        min_period: int,
        max_period: int,
    ) -> tuple[list[tuple[int, float]], np.ndarray]:
        """Find candidate periodic spacings via FFT-based autocorrelation.

        Returns:
            (candidates, autocorr) where candidates is a list of
            (period, strength) tuples sorted by strength descending,
            and autocorr is the normalized autocorrelation array.
        """
        proj = projection.astype(np.float64)
        n = len(proj)
        if n < min_period * 2:
            return [], np.array([])

        # Zero-mean and normalize
        proj = proj - np.mean(proj)
        std = np.std(proj)
        if std < 1e-10:
            return [], np.array([])
        proj = proj / std

        # FFT-based autocorrelation
        autocorr = fftconvolve(proj, proj[::-1], mode="full")
        autocorr = autocorr[n - 1 :]  # positive lags only
        zero_lag = autocorr[0]
        if zero_lag < 1e-10:
            return [], autocorr
        autocorr = autocorr / zero_lag

        # Search for peaks within cell size range
        search_start = min_period
        search_end = min(max_period + 1, len(autocorr))
        if search_start >= search_end:
            return [], autocorr

        search_region = autocorr[search_start:search_end]

        peaks, properties = find_peaks(
            search_region,
            prominence=0.05,
            distance=max(1, min_period // 2),
        )

        if len(peaks) == 0:
            return [], autocorr

        # Build candidate list sorted by strength (descending)
        candidates = []
        for peak_idx in peaks:
            period = peak_idx + search_start
            strength = float(autocorr[period])
            if strength > 0:
                candidates.append((int(period), min(1.0, strength)))

        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates, autocorr

    # Paired period selection

    @staticmethod
    def _pick_best_periods(
        h_candidates: list[tuple[int, float]],
        v_candidates: list[tuple[int, float]],
    ) -> tuple[int | None, float, int | None, float]:
        """Score all (h, v) candidate pairs and return the best match.

        Prefers pairs where both axes agree on cell size (high period ratio)
        and biases toward smaller periods (fundamentals over harmonics).

        Returns:
            (h_period, h_strength, v_period, v_strength)
        """
        if not h_candidates and not v_candidates:
            return None, 0.0, None, 0.0

        if not h_candidates:
            vp, vs = v_candidates[0]
            return None, 0.0, vp, vs

        if not v_candidates:
            hp, hs = h_candidates[0]
            return hp, hs, None, 0.0

        best_score = -1.0
        best_hp, best_hs, best_vp, best_vs = None, 0.0, None, 0.0

        for hp, hs in h_candidates:
            for vp, vs in v_candidates:
                # Period agreement: ratio close to 1.0 is better
                ratio = min(hp, vp) / max(hp, vp)
                agreement = max(0.0, ratio)

                # Combined strength
                strength = math.sqrt(hs * vs)

                # Bias toward smaller periods (fundamentals)
                max_period = max(hp, vp)
                size_bias = 1.0 / (1.0 + max_period * 0.001)

                score = agreement * strength * size_bias

                if score > best_score:
                    best_score = score
                    best_hp, best_hs = hp, hs
                    best_vp, best_vs = vp, vs

        return best_hp, best_hs, best_vp, best_vs

    # Tile count computation

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
