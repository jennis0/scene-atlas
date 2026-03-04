"""Unit tests for the color search service.

Covers:
- hex_to_hsl_cylinder(): conversion from hex colour to cylindrical HSL coordinates
- color_distance(): Euclidean distance between two 3-tuples
- ColorIndex: in-memory cache, proximity search, TTL expiry, OR-union across colours
"""

import math
from unittest.mock import MagicMock, patch

import pytest

from backend.app.services.color_search import (
    ColorIndex,
    color_distance,
    hex_to_hsl_cylinder,
)

ABS_TOL = 1e-4


def _make_mock_db(rows: list):
    """Return a mock SQLAlchemy Session whose .query().all() yields rows.

    rows: list of (image_id, color_hex) pairs, matching what
    ColorIndex._refresh() pulls from the DB.
    """
    mock_db = MagicMock()
    mock_query = MagicMock()
    mock_db.query.return_value = mock_query
    mock_query.all.return_value = rows
    return mock_db


class TestHexToHslCylinder:
    """Tests for hex_to_hsl_cylinder()."""

    def test_black(self):
        """#000000 is achromatic with zero lightness -- all coordinates are 0."""
        result = hex_to_hsl_cylinder("#000000")
        assert result == pytest.approx((0.0, 0.0, 0.0), abs=ABS_TOL)

    def test_white(self):
        """#ffffff is achromatic with full lightness -- x=0, y=0, z=1."""
        result = hex_to_hsl_cylinder("#ffffff")
        assert result == pytest.approx((0.0, 0.0, 1.0), abs=ABS_TOL)

    def test_pure_red(self):
        """Pure red: hue=0, S=1, L=0.5 -> angle=0 -> (1, 0, 0.5)."""
        result = hex_to_hsl_cylinder("#ff0000")
        assert result == pytest.approx((1.0, 0.0, 0.5), abs=ABS_TOL)

    def test_pure_green(self):
        """Pure green: hue=1/3, S=1, L=0.5 -> angle=2pi/3 -> (-0.5, 0.866, 0.5)."""
        angle = 2 * math.pi / 3
        expected = (math.cos(angle), math.sin(angle), 0.5)
        result = hex_to_hsl_cylinder("#00ff00")
        assert result == pytest.approx(expected, abs=ABS_TOL)

    def test_pure_blue(self):
        """Pure blue: hue=2/3, S=1, L=0.5 -> angle=4pi/3 -> (-0.5, -0.866, 0.5)."""
        angle = 4 * math.pi / 3
        expected = (math.cos(angle), math.sin(angle), 0.5)
        result = hex_to_hsl_cylinder("#0000ff")
        assert result == pytest.approx(expected, abs=ABS_TOL)

    def test_hash_prefix_optional(self):
        """Hex strings with and without # must produce identical output."""
        with_hash = hex_to_hsl_cylinder("#ff0000")
        without_hash = hex_to_hsl_cylinder("ff0000")
        assert with_hash == pytest.approx(without_hash, abs=ABS_TOL)

    def test_returns_three_floats(self):
        """Return value must be a 3-tuple of floats."""
        result = hex_to_hsl_cylinder("#aabbcc")
        assert len(result) == 3
        assert all(isinstance(v, float) for v in result)

    def test_gray_has_zero_saturation(self):
        """#808080 is grey: saturation=0, so x and y components are 0."""
        x, y, _lightness = hex_to_hsl_cylinder("#808080")
        assert abs(x) == pytest.approx(0.0, abs=ABS_TOL)
        assert abs(y) == pytest.approx(0.0, abs=ABS_TOL)


class TestColorDistance:
    """Tests for color_distance()."""

    def test_same_color_zero_distance(self):
        """Distance from a vector to itself is 0."""
        v = (0.3, 0.7, 0.5)
        assert color_distance(v, v) == pytest.approx(0.0, abs=ABS_TOL)

    def test_known_distance_unit_axis(self):
        """Distance from origin to (1, 0, 0) is 1.0."""
        assert color_distance((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)) == pytest.approx(1.0, abs=ABS_TOL)

    def test_max_distance_black_white(self):
        """Distance between cylindrical black (0,0,0) and (0,0,1) is 1.0."""
        assert color_distance((0.0, 0.0, 0.0), (0.0, 0.0, 1.0)) == pytest.approx(1.0, abs=ABS_TOL)

    def test_known_distance_diagonal(self):
        """Distance from (0,0,0) to (1,1,1) is sqrt(3) approx 1.732."""
        assert color_distance((0.0, 0.0, 0.0), (1.0, 1.0, 1.0)) == pytest.approx(
            math.sqrt(3), abs=ABS_TOL
        )

    def test_symmetric(self):
        """Distance is symmetric: dist(a, b) == dist(b, a)."""
        a = (0.1, 0.5, 0.9)
        b = (0.8, 0.2, 0.4)
        assert color_distance(a, b) == pytest.approx(color_distance(b, a), abs=ABS_TOL)

    def test_triangle_inequality(self):
        """Triangle inequality holds: dist(a, c) <= dist(a, b) + dist(b, c)."""
        a = (0.0, 0.0, 0.0)
        b = (0.5, 0.5, 0.5)
        c = (1.0, 0.0, 1.0)
        assert color_distance(a, c) <= color_distance(a, b) + color_distance(b, c) + ABS_TOL


class TestColorIndex:
    """Tests for ColorIndex: cache population, proximity search, TTL refresh."""

    def test_returns_matching_images(self):
        """An image whose stored colour matches the target hex exactly is returned."""
        mock_db = _make_mock_db(
            [
                (42, "#ff0000"),
                (7, "#0000ff"),
                (99, "#000000"),
            ]
        )
        index = ColorIndex()
        result = index.find_images_by_color(mock_db, "#ff0000", threshold=0.1)
        assert 42 in result

    def test_threshold_excludes_distant_images(self):
        """With a very tight threshold, only near-exact matches are returned."""
        mock_db = _make_mock_db(
            [
                (1, "#ff0000"),
                (2, "#0000ff"),
            ]
        )
        index = ColorIndex()
        result = index.find_images_by_color(mock_db, "#ff0000", threshold=0.01)
        assert 1 in result
        assert 2 not in result

    def test_empty_db_returns_empty_set(self):
        """No Color rows in the DB -> find_images_by_color returns an empty set."""
        mock_db = _make_mock_db([])
        index = ColorIndex()
        result = index.find_images_by_color(mock_db, "#ff0000", threshold=10.0)
        assert result == set()

    def test_find_by_multiple_colors_union(self):
        """find_images_by_colors applies OR logic: any matching colour includes the image."""
        mock_db = _make_mock_db(
            [
                (1, "#ff0000"),
                (2, "#0000ff"),
            ]
        )
        index = ColorIndex()
        result = index.find_images_by_colors(mock_db, ["#ff0000", "#0000ff"], threshold=0.1)
        assert 1 in result
        assert 2 in result

    def test_find_by_multiple_colors_no_duplicates(self):
        """An image matching several target colours appears only once in the result set."""
        mock_db = _make_mock_db(
            [
                (1, "#ff0000"),
                (1, "#fe0000"),
            ]
        )
        index = ColorIndex()
        result = index.find_images_by_colors(mock_db, ["#ff0000", "#fe0000"], threshold=0.2)
        assert isinstance(result, set)
        assert 1 in result

    def test_cache_loaded_once_for_multiple_calls(self):
        """When TTL has not expired the DB is queried only once."""
        mock_db = _make_mock_db([(1, "#ff0000")])
        index = ColorIndex()

        index.find_images_by_color(mock_db, "#ff0000", threshold=0.1)
        index.find_images_by_color(mock_db, "#ff0000", threshold=0.1)
        index.find_images_by_color(mock_db, "#ff0000", threshold=0.1)

        assert mock_db.query.return_value.all.call_count == 1

    def test_cache_refresh_after_ttl(self):
        """After the 60-second TTL expires the DB is queried again on the next search."""
        mock_db = _make_mock_db([(1, "#ff0000")])
        index = ColorIndex()

        with patch("backend.app.services.color_search.time.monotonic") as mock_time:
            mock_time.return_value = 0.0
            index.find_images_by_color(mock_db, "#ff0000", threshold=0.1)

            mock_time.return_value = 30.0
            index.find_images_by_color(mock_db, "#ff0000", threshold=0.1)

            mock_time.return_value = 61.0
            index.find_images_by_color(mock_db, "#ff0000", threshold=0.1)

        # Two DB queries: one at t=0, one after TTL expiry at t=61.
        assert mock_db.query.return_value.all.call_count == 2


class TestColorIndexConcurrency:
    def test_concurrent_refresh_no_errors(self, tmp_db):
        """Concurrent calls to _ensure_loaded don't crash or deadlock."""
        import threading

        _, SessionLocal = tmp_db
        index = ColorIndex()
        errors = []

        def reader():
            with SessionLocal() as db:
                for _ in range(20):
                    try:
                        index._loaded_at = 0.0  # Force TTL expiry
                        index._ensure_loaded(db)
                    except Exception as e:  # noqa: BLE001
                        errors.append(e)

        threads = [threading.Thread(target=reader) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors, f"Concurrent refresh raised: {errors}"
