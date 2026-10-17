"""Grid detection plumbing: memory estimates, which images the backfill touches, and
how file-name grid sizes are oriented."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.pipeline.backfill_grid_detection import detection_mode
from backend.pipeline.ingest_process import _detect_grid, grid_detection_bytes, orient_grid
from backend.pipeline.pipeline_config import PipelineConfig

MB = 1024 * 1024
FULL = PipelineConfig()
LIMITED = PipelineConfig(grid_analysis_max_dim=4096)


# ---------------------------------------------------------------------------
# Memory estimate (fitted on measured peak RSS, design/grid-detection-v3.md round 5)
# ---------------------------------------------------------------------------


def test_baseline_jpeg_estimate():
    # 10000 x 6000 = 60 Mpx: (42 + 2.0 * 60) * 1.8 MB
    assert grid_detection_bytes(10_000, 6_000, "JPEG", False, FULL) == int(291.6 * MB)


def test_progressive_jpeg_costs_more_per_pixel():
    baseline = grid_detection_bytes(10_000, 6_000, "JPEG", False, FULL)
    progressive = grid_detection_bytes(10_000, 6_000, "JPEG", True, FULL)
    assert progressive > baseline


def test_limit_only_shrinks_baseline_jpeg():
    """DCT-scaled decode exists only for baseline JPEG; other formats decode in full."""
    assert grid_detection_bytes(10_000, 6_000, "JPEG", False, LIMITED) < grid_detection_bytes(
        10_000, 6_000, "JPEG", False, FULL
    )
    for fmt, progressive in (("JPEG", True), ("PNG", False), ("WEBP", False)):
        assert grid_detection_bytes(10_000, 6_000, fmt, progressive, LIMITED) == (
            grid_detection_bytes(10_000, 6_000, fmt, progressive, FULL)
        )


def test_unknown_formats_use_the_most_conservative_estimate():
    tiff = grid_detection_bytes(8_000, 8_000, "TIFF", False, FULL)
    assert tiff == grid_detection_bytes(8_000, 8_000, "WEBP", False, FULL)
    assert tiff >= grid_detection_bytes(8_000, 8_000, "PNG", False, FULL)


# ---------------------------------------------------------------------------
# Backfill eligibility
# ---------------------------------------------------------------------------


def _image(**kw):
    defaults = {
        "image_type": "battlemap",
        "media_type": "image",
        "grid_source": None,
        "gridded": None,
        "grid_width": None,
        "grid_confidence": None,
    }
    return SimpleNamespace(**{**defaults, **kw})


@pytest.mark.parametrize("force", [False, True])
def test_user_set_grids_are_never_touched(force):
    assert detection_mode(_image(grid_source="user", gridded=True), force) is None


@pytest.mark.parametrize("force", [False, True])
def test_explicit_file_name_labels_are_trusted(force):
    no_grid = _image(grid_source="filename", gridded=False)
    exact_size = _image(grid_source="filename", gridded=True, grid_width=30)
    assert detection_mode(no_grid, force) is None
    assert detection_mode(exact_size, force) is None


def test_file_name_gridded_without_size_gets_size_detection():
    image = _image(grid_source="filename", gridded=True)
    assert detection_mode(image, force=False) == "size"


def test_detected_size_is_only_redone_with_force():
    image = _image(grid_source="filename", gridded=True, grid_width=30, grid_confidence=0.8)
    assert detection_mode(image, force=False) is None
    assert detection_mode(image, force=True) == "size"


def test_unknown_grid_gets_full_detection():
    assert detection_mode(_image(), force=False) == "full"


def test_detector_results_are_only_redone_with_force():
    image = _image(grid_source="detector", gridded=False, grid_confidence=0.1)
    assert detection_mode(image, force=False) is None
    assert detection_mode(image, force=True) == "full"


@pytest.mark.parametrize(
    "kw", [{"image_type": "scene"}, {"media_type": "video"}], ids=["scene", "video"]
)
def test_non_battlemaps_are_skipped(kw):
    assert detection_mode(_image(**kw), force=True) is None


# ---------------------------------------------------------------------------
# File-name NxM orientation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("grid", "image", "expected"),
    [
        ((30, 20), (3000, 2000), (30, 20)),  # already matches a landscape map
        ((20, 30), (3000, 2000), (30, 20)),  # rows x columns on a landscape map
        ((30, 20), (2000, 3000), (20, 30)),  # a landscape NxM on a portrait map
        ((20, 30), (2000, 3000), (20, 30)),
        ((30, 30), (2000, 3000), (30, 30)),  # square grid: nothing to orient
        ((30, 20), (3000, 3000), (30, 20)),  # square image: keep the name's order
        ((30, 20), (2980, 3000), (30, 20)),  # within 2% of square: still ambiguous
        ((30, 20), (2900, 3000), (20, 30)),  # beyond the tolerance
    ],
)
def test_file_name_grid_follows_the_image_orientation(grid, image, expected):
    assert orient_grid(*grid, *image) == expected


@pytest.mark.parametrize("args", [(None, None, 3000, 2000), (20, 30, None, None), (20, 30, 0, 0)])
def test_orientation_needs_both_sizes(args):
    assert orient_grid(*args) == args[:2]


def test_ingest_stores_the_file_name_grid_oriented():
    item = SimpleNamespace(
        image_type="battlemap",
        parsed={"gridded": True, "grid_width": 20, "grid_height": 30, "grid_type": None},
    )
    cfg = PipelineConfig(enable_image_grid_detection=False)
    grid = _detect_grid(item, Path("unused.jpg"), 3000, 2000, cfg)
    assert (grid["grid_width"], grid["grid_height"]) == (30, 20)
    assert grid["grid_source"] == "filename"
