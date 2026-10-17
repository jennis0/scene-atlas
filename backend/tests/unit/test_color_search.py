"""Colour search: hex to CIELAB conversion and the SQL delta E query."""

import math

import pytest

from backend.app.colorspace import hex_to_lab
from backend.app.models import Color, Image
from backend.app.models.schemas import AppSettingsPatch
from backend.app.services.app_settings import update_settings
from backend.app.services.color_search import color_match_ids, find_images_by_colors

# sRGB (D65) references, as published by Bruce Lindbloom's calculator.
REFERENCE_LAB = {
    "#000000": (0.0, 0.0, 0.0),
    "#ffffff": (100.0, 0.0, 0.0),
    "#808080": (53.585, 0.0, 0.0),
    "#ff0000": (53.2408, 80.0925, 67.2032),
    "#00ff00": (87.7347, -86.1827, 83.1793),
    "#0000ff": (32.2970, 79.1875, -107.8602),
    "#ffff00": (97.1393, -21.5537, 94.4780),
}


class TestHexToLab:
    @pytest.mark.parametrize("hex_val", REFERENCE_LAB)
    def test_reference_values(self, hex_val):
        assert hex_to_lab(hex_val) == pytest.approx(REFERENCE_LAB[hex_val], abs=1e-3)

    def test_hash_prefix_and_case_ignored(self):
        assert hex_to_lab("D4A853") == pytest.approx(hex_to_lab("#d4a853"))

    def test_model_sets_lab_from_hex(self):
        color = Color(image_id=1, color_hex="#ff0000")
        assert (color.lab_l, color.lab_a, color.lab_b) == pytest.approx(REFERENCE_LAB["#ff0000"])
        color.color_hex = "#0000ff"
        assert color.lab_b == pytest.approx(REFERENCE_LAB["#0000ff"][2])


def _delta_e(h1: str, h2: str) -> float:
    return math.dist(hex_to_lab(h1), hex_to_lab(h2))


@pytest.fixture
def library(db_session):
    """One image per colour; returns ``{hex: image_id}``."""

    def add(*hexes: str) -> dict[str, int]:
        ids = {}
        for hex_val in hexes:
            image = Image(
                filename=f"{hex_val[1:]}.jpg", storage_key=f"{hex_val[1:]}.jpg", name=hex_val
            )
            db_session.add(image)
            db_session.flush()
            db_session.add(Color(image_id=image.id, color_hex=hex_val, color_order=1))
            ids[hex_val] = image.id
        db_session.commit()
        return ids

    return add


class TestFindImagesByColors:
    def test_threshold_boundary(self, db_session, library):
        """A colour just inside the threshold matches; one just outside doesn't."""
        ids = library("#808080", "#8a8a8a", "#a0a0a0")
        near = _delta_e("#808080", "#8a8a8a")
        far = _delta_e("#808080", "#a0a0a0")
        assert near < far
        threshold = (near + far) / 2
        assert find_images_by_colors(db_session, ["#808080"], threshold) == {
            ids["#808080"],
            ids["#8a8a8a"],
        }
        assert find_images_by_colors(db_session, ["#808080"], near + 1e-6) == {
            ids["#808080"],
            ids["#8a8a8a"],
        }
        assert find_images_by_colors(db_session, ["#808080"], near - 1e-6) == {ids["#808080"]}

    def test_box_corner_outside_sphere_excluded(self, db_session, library):
        """Inside the per-axis bounding box but beyond the Euclidean distance."""
        ids = library("#808080", "#9a7aa0")
        target_lab = hex_to_lab("#808080")
        offsets = [abs(x - y) for x, y in zip(hex_to_lab("#9a7aa0"), target_lab, strict=True)]
        threshold = max(offsets) + 0.5
        assert _delta_e("#808080", "#9a7aa0") > threshold
        assert find_images_by_colors(db_session, ["#808080"], threshold) == {ids["#808080"]}

    def test_or_across_colours(self, db_session, library):
        ids = library("#ff0000", "#0000ff", "#00ff00")
        result = find_images_by_colors(db_session, ["#fe0101", "#0101fe"], 5.0)
        assert result == {ids["#ff0000"], ids["#0000ff"]}

    def test_image_matching_several_colours_returned_once(self, db_session, library):
        ids = library("#ff0000")
        db_session.add(Color(image_id=ids["#ff0000"], color_hex="#fe0000", color_order=2))
        db_session.commit()
        assert find_images_by_colors(db_session, ["#ff0000", "#fe0000"], 5.0) == {ids["#ff0000"]}

    def test_no_targets_or_no_rows(self, db_session, library):
        assert find_images_by_colors(db_session, ["#ff0000"], 50.0) == set()
        library("#ff0000")
        assert find_images_by_colors(db_session, [], 50.0) == set()

    def test_threshold_defaults_to_app_setting(self, db_session, library):
        ids = library("#808080", "#a0a0a0")
        gap = _delta_e("#808080", "#a0a0a0")
        update_settings(db_session, AppSettingsPatch(color_distance_threshold=gap - 1))
        assert find_images_by_colors(db_session, ["#808080"]) == {ids["#808080"]}
        update_settings(db_session, AppSettingsPatch(color_distance_threshold=gap + 1))
        assert find_images_by_colors(db_session, ["#808080"]) == set(ids.values())

    def test_or_across_colours_sharing_a_scan(self, db_session, library):
        """Targets with overlapping L* ranges share one index scan but keep their own a*/b*."""
        ids = library("#ff0000", "#808080", "#00a8a8", "#0000ff")
        assert abs(hex_to_lab("#ff0000")[0] - hex_to_lab("#808080")[0]) < 1
        result = find_images_by_colors(db_session, ["#fe0101", "#818181"], 5.0)
        assert result == {ids["#ff0000"], ids["#808080"]}

    @pytest.mark.parametrize(
        "targets", [["#808080"], ["#808080", "#ff0000"], ["#808080", "#ffffff", "#000000"]]
    )
    def test_query_uses_lab_index(self, db_session, targets):
        stmt = color_match_ids(targets, 10.0)
        compiled = stmt.compile(
            dialect=db_session.bind.dialect, compile_kwargs={"literal_binds": True}
        )
        plan = [
            str(row[-1])
            for row in db_session.connection().exec_driver_sql(f"EXPLAIN QUERY PLAN {compiled}")
        ]
        scans = [line for line in plan if "colors" in line]
        assert scans
        assert all(
            line.startswith("SEARCH colors USING COVERING INDEX ix_colors_lab") for line in scans
        )
