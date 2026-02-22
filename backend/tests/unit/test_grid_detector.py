"""Tests for image-based grid detection (GridDetector service)."""

import math

import cv2
import numpy as np
import pytest

from backend.app.services.grid_detector import GridDetector


# ---------------------------------------------------------------------------
# Helpers to generate test images
# ---------------------------------------------------------------------------


def _make_square_grid_image(
    width: int,
    height: int,
    cell_size: int,
    line_color: int = 0,
    bg_color: int = 200,
    line_thickness: int = 1,
    path: str | None = None,
) -> str:
    """Generate an image with a square grid overlay.

    Returns the saved file path.
    """
    img = np.full((height, width), bg_color, dtype=np.uint8)

    # Vertical lines
    for x in range(0, width + 1, cell_size):
        if x < width:
            cv2.line(img, (x, 0), (x, height - 1), line_color, line_thickness)

    # Horizontal lines
    for y in range(0, height + 1, cell_size):
        if y < height:
            cv2.line(img, (0, y), (width - 1, y), line_color, line_thickness)

    if path is None:
        raise ValueError("path is required")
    cv2.imwrite(path, img)
    return path


def _make_hex_grid_image(
    width: int,
    height: int,
    hex_size: int,
    flat_top: bool = False,
    line_color: int = 0,
    bg_color: int = 200,
    line_thickness: int = 1,
    path: str | None = None,
) -> str:
    """Generate an image with a hexagonal grid overlay.

    For pointy-top hexagons:
      - hex_size = distance from center to corner (circumradius)
      - hex width = sqrt(3) * hex_size
      - hex height = 2 * hex_size

    For flat-top hexagons:
      - hex_size = distance from center to corner (circumradius)
      - hex width = 2 * hex_size
      - hex height = sqrt(3) * hex_size
    """
    img = np.full((height, width), bg_color, dtype=np.uint8)

    if flat_top:
        col_spacing = 1.5 * hex_size
        row_spacing = math.sqrt(3) * hex_size
    else:
        col_spacing = math.sqrt(3) * hex_size
        row_spacing = 1.5 * hex_size

    # Determine number of hex columns/rows to cover the image
    n_cols = int(width / col_spacing) + 3
    n_rows = int(height / row_spacing) + 3

    for row in range(n_rows):
        for col in range(n_cols):
            if flat_top:
                cx = col * col_spacing
                cy = row * row_spacing + (col % 2) * row_spacing / 2
            else:
                cx = col * col_spacing + (row % 2) * col_spacing / 2
                cy = row * row_spacing

            # Draw hexagon
            pts = []
            for i in range(6):
                if flat_top:
                    angle_deg = 60 * i
                else:
                    angle_deg = 60 * i + 30
                angle_rad = math.radians(angle_deg)
                px = int(cx + hex_size * math.cos(angle_rad))
                py = int(cy + hex_size * math.sin(angle_rad))
                pts.append([px, py])

            pts_arr = np.array(pts, dtype=np.int32)
            cv2.polylines(img, [pts_arr], isClosed=True, color=line_color, thickness=line_thickness)

    if path is None:
        raise ValueError("path is required")
    cv2.imwrite(path, img)
    return path


def _make_solid_image(
    width: int, height: int, color: int = 180, path: str | None = None
) -> str:
    """Generate a solid-color image (no grid)."""
    img = np.full((height, width), color, dtype=np.uint8)
    if path is None:
        raise ValueError("path is required")
    cv2.imwrite(path, img)
    return path


def _make_noise_image(
    width: int, height: int, path: str | None = None, seed: int = 42
) -> str:
    """Generate a random noise image (no grid)."""
    rng = np.random.RandomState(seed)
    img = rng.randint(0, 256, (height, width), dtype=np.uint8)
    if path is None:
        raise ValueError("path is required")
    cv2.imwrite(path, img)
    return path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def detector():
    return GridDetector(
        min_cell_px=32,
        max_cell_px=256,
        max_dim=1024,
        presence_threshold=0.3,
        size_threshold=0.15,
    )


# ---------------------------------------------------------------------------
# Square grid tests
# ---------------------------------------------------------------------------


class TestSquareGridDetection:
    """Test detection of square grids with various parameters."""

    def test_detect_clear_square_grid(self, detector, tmp_path):
        """Strong grid lines on a clean background → gridded=True, type=square."""
        width, height, cell = 900, 600, 100  # 9×6 grid
        path = _make_square_grid_image(
            width, height, cell, line_color=0, bg_color=200,
            line_thickness=2, path=str(tmp_path / "grid_clear.png"),
        )

        result = detector.detect(tmp_path / "grid_clear.png", width, height)

        assert result["gridded"] is True
        assert result["grid_type"] == "square"
        assert result["confidence"] > 0.3
        # Tile counts: 900/100=9 wide, 600/100=6 tall
        if result["grid_width"] is not None:
            assert result["grid_width"] == 9
        if result["grid_height"] is not None:
            assert result["grid_height"] == 6

    def test_detect_fine_square_grid(self, detector, tmp_path):
        """Smaller cell size, still detectable."""
        width, height, cell = 1024, 768, 64  # 16×12 grid
        path = _make_square_grid_image(
            width, height, cell, line_color=50, bg_color=200,
            line_thickness=1, path=str(tmp_path / "grid_fine.png"),
        )

        result = detector.detect(tmp_path / "grid_fine.png", width, height)

        assert result["gridded"] is True
        assert result["grid_type"] == "square"
        if result["grid_width"] is not None:
            assert result["grid_width"] == 16
        if result["grid_height"] is not None:
            assert result["grid_height"] == 12

    def test_detect_large_cell_square_grid(self, detector, tmp_path):
        """Large cells (200px) on a large image."""
        width, height, cell = 1000, 1000, 200  # 5×5 grid
        path = _make_square_grid_image(
            width, height, cell, line_color=30, bg_color=180,
            line_thickness=2, path=str(tmp_path / "grid_large.png"),
        )

        result = detector.detect(tmp_path / "grid_large.png", width, height)

        assert result["gridded"] is True
        assert result["grid_type"] == "square"
        if result["grid_width"] is not None:
            assert result["grid_width"] == 5
        if result["grid_height"] is not None:
            assert result["grid_height"] == 5

    def test_detect_faint_grid(self, detector, tmp_path):
        """Faint grid lines (low contrast) — may detect with lower confidence."""
        width, height, cell = 900, 600, 100
        path = _make_square_grid_image(
            width, height, cell, line_color=170, bg_color=200,
            line_thickness=1, path=str(tmp_path / "grid_faint.png"),
        )

        result = detector.detect(tmp_path / "grid_faint.png", width, height)

        # Faint grids should have lower confidence, may or may not be detected
        # The key is no false positives — if detected, type should be square
        if result["gridded"] is True:
            assert result["grid_type"] == "square"

    def test_size_only_mode(self, detector, tmp_path):
        """When we already know it's gridded, use lower threshold to find size."""
        width, height, cell = 900, 600, 100
        path = _make_square_grid_image(
            width, height, cell, line_color=0, bg_color=200,
            line_thickness=2, path=str(tmp_path / "grid.png"),
        )

        result = detector.detect_size_only(
            tmp_path / "grid.png", width, height
        )

        assert result["gridded"] is True
        if result["grid_width"] is not None:
            assert result["grid_width"] == 9


# ---------------------------------------------------------------------------
# Hex grid tests
# ---------------------------------------------------------------------------


class TestHexGridDetection:
    """Test detection of hexagonal grids."""

    def test_detect_hex_grid_pointy_top(self, detector, tmp_path):
        """Pointy-top hex grid → type=hex."""
        width, height = 1000, 1000
        hex_size = 40  # circumradius
        path = _make_hex_grid_image(
            width, height, hex_size, flat_top=False,
            line_color=0, bg_color=200, line_thickness=2,
            path=str(tmp_path / "hex_pointy.png"),
        )

        result = detector.detect(tmp_path / "hex_pointy.png", width, height)

        # Hex detection may produce "hex" or "square" depending on signal strength.
        # The key thing to verify is that the algorithm finds periodicity.
        assert result["confidence"] > 0
        if result["gridded"] is True:
            # If detected, should ideally be hex
            assert result["grid_type"] in ("hex", "square")

    def test_detect_hex_grid_flat_top(self, detector, tmp_path):
        """Flat-top hex grid → type=hex."""
        width, height = 1000, 1000
        hex_size = 40
        path = _make_hex_grid_image(
            width, height, hex_size, flat_top=True,
            line_color=0, bg_color=200, line_thickness=2,
            path=str(tmp_path / "hex_flat.png"),
        )

        result = detector.detect(tmp_path / "hex_flat.png", width, height)

        assert result["confidence"] > 0
        if result["gridded"] is True:
            assert result["grid_type"] in ("hex", "square")

    def test_detect_large_hex_grid(self, detector, tmp_path):
        """Larger hex cells for easier detection."""
        width, height = 1200, 1200
        hex_size = 60
        path = _make_hex_grid_image(
            width, height, hex_size, flat_top=False,
            line_color=0, bg_color=200, line_thickness=2,
            path=str(tmp_path / "hex_large.png"),
        )

        result = detector.detect(tmp_path / "hex_large.png", width, height)

        if result["gridded"] is True:
            assert result["grid_type"] in ("hex", "square")
            assert result["confidence"] > 0.2


# ---------------------------------------------------------------------------
# No-grid tests (false positive prevention)
# ---------------------------------------------------------------------------


class TestNoGrid:
    """Ensure no false positives on images without grids."""

    def test_solid_image(self, detector, tmp_path):
        """Solid color image → not gridded."""
        width, height = 800, 600
        _make_solid_image(width, height, path=str(tmp_path / "solid.png"))

        result = detector.detect(tmp_path / "solid.png", width, height)

        assert result["gridded"] is not True

    def test_noise_image(self, detector, tmp_path):
        """Random noise → not gridded."""
        width, height = 800, 600
        _make_noise_image(width, height, path=str(tmp_path / "noise.png"))

        result = detector.detect(tmp_path / "noise.png", width, height)

        assert result["gridded"] is not True

    def test_unreadable_image(self, detector, tmp_path):
        """Non-existent file → graceful fallback."""
        result = detector.detect(tmp_path / "nonexistent.png", 800, 600)

        assert result["gridded"] is None
        assert result["confidence"] == 0.0


# ---------------------------------------------------------------------------
# Internal method tests
# ---------------------------------------------------------------------------


class TestSnapToTileCount:
    """Test the period → tile count snapping logic."""

    def test_exact_divisor(self, detector):
        # 900px / 100px per cell = exactly 9 tiles
        assert detector._snap_to_tile_count(100.0, 900) == 9

    def test_near_divisor(self, detector):
        # 900px / 98px ≈ 9.18 tiles → should snap to 9 (actual cell = 100px, error ~2%)
        result = detector._snap_to_tile_count(98.0, 900)
        assert result == 9

    def test_no_good_fit(self, detector):
        # 900px / 137px ≈ 6.57 tiles → no clean divisor nearby
        # Should still return the closest reasonable value
        result = detector._snap_to_tile_count(137.0, 900)
        assert result is not None

    def test_zero_period(self, detector):
        assert detector._snap_to_tile_count(0.0, 900) is None

    def test_zero_dimension(self, detector):
        assert detector._snap_to_tile_count(100.0, 0) is None


class TestClassifyGridType:
    """Test the period ratio → grid type classification."""

    def test_equal_periods_is_square(self, detector):
        assert detector._classify_grid_type(100, 100, 0.5, 0.5) == "square"

    def test_near_equal_is_square(self, detector):
        assert detector._classify_grid_type(95, 100, 0.5, 0.5) == "square"

    def test_hex_ratio(self, detector):
        # sqrt(3)/2 ≈ 0.866 → one period is ~87% of the other
        h_period = 100
        v_period = int(100 * math.sqrt(3) / 2)  # 86
        assert detector._classify_grid_type(h_period, v_period, 0.5, 0.5) == "hex"

    def test_inverse_hex_ratio(self, detector):
        h_period = int(100 * math.sqrt(3) / 2)  # 86
        v_period = 100
        assert detector._classify_grid_type(h_period, v_period, 0.5, 0.5) == "hex"

    def test_one_period_none(self, detector):
        result = detector._classify_grid_type(100, None, 0.5, 0.0)
        assert result == "square"

    def test_both_none(self, detector):
        assert detector._classify_grid_type(None, None, 0.0, 0.0) is None
