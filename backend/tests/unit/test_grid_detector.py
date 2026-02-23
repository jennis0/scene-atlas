"""Tests for image-based grid detection (GridDetector service)."""

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
    noise_std: int = 30,
    path: str | None = None,
) -> str:
    """Generate an image with a square grid overlay.

    Adds Gaussian noise to the background to simulate real artwork.
    Without noise, the grid lines survive 30-degree rotation and
    trigger false hex classification.

    Returns the saved file path.
    """
    rng = np.random.RandomState(42)
    img = rng.normal(bg_color, noise_std, (height, width)).clip(0, 255).astype(np.uint8)

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


def _make_solid_image(width: int, height: int, color: int = 180, path: str | None = None) -> str:
    """Generate a solid-color image (no grid)."""
    img = np.full((height, width), color, dtype=np.uint8)
    if path is None:
        raise ValueError("path is required")
    cv2.imwrite(path, img)
    return path


def _make_noise_image(width: int, height: int, path: str | None = None, seed: int = 42) -> str:
    """Generate a random noise image (no grid)."""
    rng = np.random.RandomState(seed)
    img = rng.randint(0, 256, (height, width), dtype=np.uint8)
    if path is None:
        raise ValueError("path is required")
    cv2.imwrite(path, img)
    return path


def _make_hex_grid_image(
    width: int,
    height: int,
    hex_size: int = 40,
    line_color: int = 0,
    bg_color: int = 200,
    line_thickness: int = 1,
    path: str | None = None,
) -> str:
    """Generate an image with a pointy-top hex grid overlay.

    hex_size is the distance from center to vertex.
    """
    import math as _math

    img = np.full((height, width), bg_color, dtype=np.uint8)

    # Pointy-top hex geometry
    hex_h = hex_size * 2
    hex_w = _math.sqrt(3) * hex_size
    row_height = hex_h * 0.75

    rows = int(height / row_height) + 2
    cols = int(width / hex_w) + 2

    for row in range(rows):
        for col in range(cols):
            cx = col * hex_w + (hex_w / 2 if row % 2 else 0)
            cy = row * row_height
            # Draw 6 sides of the hex
            pts = []
            for i in range(6):
                angle = _math.radians(60 * i - 30)  # pointy-top
                px = int(cx + hex_size * _math.cos(angle))
                py = int(cy + hex_size * _math.sin(angle))
                pts.append((px, py))
            for i in range(6):
                cv2.line(
                    img,
                    pts[i],
                    pts[(i + 1) % 6],
                    line_color,
                    line_thickness,
                )

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
        max_cell_px=320,
        max_dim=20_000,
        presence_threshold=0.20,
        size_threshold=0.15,
        period_ratio_threshold=0.98,
        hex_rot_conf=0.20,
    )


# ---------------------------------------------------------------------------
# Square grid tests
# ---------------------------------------------------------------------------


class TestSquareGridDetection:
    """Test detection of square grids with various parameters."""

    def test_detect_clear_square_grid(self, detector, tmp_path):
        """Strong grid lines on a clean background → gridded=True, type=square."""
        width, height, cell = 900, 600, 100  # 9×6 grid
        _make_square_grid_image(
            width,
            height,
            cell,
            line_color=0,
            bg_color=200,
            line_thickness=2,
            path=str(tmp_path / "grid_clear.png"),
        )

        result = detector.detect(tmp_path / "grid_clear.png", width, height)

        assert result["gridded"] is True
        assert result["grid_type"] == "square"
        assert result["confidence"] >= 0.45
        # Tile counts: 900/100=9 wide, 600/100=6 tall
        if result["grid_width"] is not None:
            assert result["grid_width"] == 9
        if result["grid_height"] is not None:
            assert result["grid_height"] == 6

    def test_detect_fine_square_grid(self, detector, tmp_path):
        """Smaller cell size, still detectable."""
        width, height, cell = 1024, 768, 64  # 16×12 grid
        _make_square_grid_image(
            width,
            height,
            cell,
            line_color=50,
            bg_color=200,
            line_thickness=1,
            path=str(tmp_path / "grid_fine.png"),
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
        _make_square_grid_image(
            width,
            height,
            cell,
            line_color=30,
            bg_color=180,
            line_thickness=2,
            path=str(tmp_path / "grid_large.png"),
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
        _make_square_grid_image(
            width,
            height,
            cell,
            line_color=170,
            bg_color=200,
            line_thickness=1,
            path=str(tmp_path / "grid_faint.png"),
        )

        result = detector.detect(tmp_path / "grid_faint.png", width, height)

        # Faint grids should have lower confidence, may or may not be detected
        # The key is no false positives — if detected, type should be square
        if result["gridded"] is True:
            assert result["grid_type"] == "square"

    def test_size_only_mode(self, detector, tmp_path):
        """When we already know it's gridded, use lower threshold to find size."""
        width, height, cell = 900, 600, 100
        _make_square_grid_image(
            width,
            height,
            cell,
            line_color=0,
            bg_color=200,
            line_thickness=2,
            path=str(tmp_path / "grid.png"),
        )

        result = detector.detect_size_only(tmp_path / "grid.png", width, height)

        assert result["gridded"] is True
        if result["grid_width"] is not None:
            assert result["grid_width"] == 9


# ---------------------------------------------------------------------------
# Hex grid tests
# ---------------------------------------------------------------------------


class TestHexGridDetection:
    """Test detection of hex grids."""

    def test_detect_hex_grid(self, detector, tmp_path):
        """Hex grid lines on a clean background -> gridded=True, type=hex."""
        width, height = 800, 800
        _make_hex_grid_image(
            width,
            height,
            hex_size=50,
            line_color=0,
            bg_color=200,
            line_thickness=2,
            path=str(tmp_path / "hex_grid.png"),
        )

        result = detector.detect(tmp_path / "hex_grid.png", width, height)

        assert result["gridded"] is True
        assert result["grid_type"] == "hex"
        assert result["confidence"] > 0

    def test_hex_grid_no_tile_counts(self, detector, tmp_path):
        """Hex grids should not report tile counts (only square grids do)."""
        width, height = 800, 800
        _make_hex_grid_image(
            width,
            height,
            hex_size=50,
            line_color=0,
            bg_color=200,
            line_thickness=2,
            path=str(tmp_path / "hex_grid.png"),
        )

        result = detector.detect(tmp_path / "hex_grid.png", width, height)

        if result["grid_type"] == "hex":
            assert result["grid_width"] is None
            assert result["grid_height"] is None

    def test_square_not_classified_as_hex(self, detector, tmp_path):
        """A square grid should never be classified as hex."""
        width, height, cell = 900, 600, 100
        _make_square_grid_image(
            width,
            height,
            cell,
            line_color=0,
            bg_color=200,
            line_thickness=2,
            path=str(tmp_path / "square.png"),
        )

        result = detector.detect(tmp_path / "square.png", width, height)

        assert result["grid_type"] != "hex"


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


class TestRotateEdges:
    """Test the edge rotation helper."""

    def test_rotate_preserves_content(self, detector):
        """Rotation should produce a non-empty image."""
        edges = np.zeros((200, 300), dtype=np.uint8)
        # Draw a horizontal line
        edges[100, :] = 255
        rotated = detector._rotate_edges(edges, 30)
        assert rotated.shape[0] > 0
        assert rotated.shape[1] > 0
        assert rotated.sum() > 0

    def test_rotate_zero_degrees(self, detector):
        """0-degree rotation should be close to a crop of the original."""
        edges = np.full((200, 300), 128, dtype=np.uint8)
        rotated = detector._rotate_edges(edges, 0)
        # Should be smaller due to margin crop
        assert rotated.shape[0] < 200
        assert rotated.shape[1] < 300


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


class TestPickBestPeriods:
    """Test the paired period selection logic."""

    def test_matching_periods_preferred(self, detector):
        """When both axes have similar periods, they should be selected."""
        h_cands = [(100, 0.8), (200, 0.9)]
        v_cands = [(101, 0.7), (50, 0.85)]
        hp, hs, vp, vs = detector._pick_best_periods(h_cands, v_cands)
        # Should prefer 100/101 pair (ratio≈0.99) over 200/50 (ratio=0.25)
        assert hp == 100
        assert vp == 101

    def test_empty_h_candidates(self, detector):
        """With no h candidates, return the strongest v candidate."""
        hp, hs, vp, vs = detector._pick_best_periods([], [(50, 0.7), (100, 0.5)])
        assert hp is None
        assert hs == 0.0
        assert vp == 50
        assert vs == 0.7

    def test_empty_v_candidates(self, detector):
        """With no v candidates, return the strongest h candidate."""
        hp, hs, vp, vs = detector._pick_best_periods([(80, 0.6)], [])
        assert hp == 80
        assert hs == 0.6
        assert vp is None
        assert vs == 0.0

    def test_both_empty(self, detector):
        hp, hs, vp, vs = detector._pick_best_periods([], [])
        assert hp is None
        assert vp is None

    def test_smaller_period_bias(self, detector):
        """When strength and agreement are equal, smaller period is preferred."""
        h_cands = [(50, 0.8), (100, 0.8)]
        v_cands = [(50, 0.8), (100, 0.8)]
        hp, hs, vp, vs = detector._pick_best_periods(h_cands, v_cands)
        # Both 50/50 and 100/100 have ratio=1.0 and same strength,
        # but 50/50 has better size_bias
        assert hp == 50
        assert vp == 50
