"""Pure rules behind Auto image type on import (design/ingestion.md §5.6)."""

from pathlib import Path

from backend.pipeline.ingest_process import DecodedItem, DecodePlan, finish_peak_bytes
from backend.pipeline.ingest_queue import ClaimedItem, effective_parsed
from backend.pipeline.pipeline_config import PipelineConfig
from backend.pipeline.stored_format import StoredFormat

PARSED = {
    "name": "Keep",
    "tags": [{"category": "feature", "value": "gridded"}],
    "scene_tags": [],
    "gridded": True,
    "grid_width": 20,
    "grid_height": 30,
    "grid_type": "square",
}


def test_effective_parse_of_a_scene_drops_the_file_names_grid():
    scene = effective_parsed("scene", PARSED)
    assert scene["tags"] == []
    assert all(scene[k] is None for k in ("gridded", "grid_width", "grid_height", "grid_type"))
    assert scene["name"] == "Keep"


def test_effective_parse_of_a_map_or_a_fixed_scene_is_unchanged():
    assert effective_parsed("battlemap", PARSED) is PARSED
    fixed_scene = {k: v for k, v in PARSED.items() if k != "scene_tags"}
    assert effective_parsed("scene", fixed_scene) is fixed_scene


def _decoded(image_type: str, kind: str = "image") -> DecodedItem:
    item = ClaimedItem(
        id=1,
        job_id="j",
        import_group_id=None,
        kind=kind,
        relative_path="a.png",
        filename="a.png",
        image_type=image_type,
        parsed={},
        staging_key=None,
        source_hash=None,
        attempts=1,
        allow_duplicate=False,
    )
    plan = DecodePlan(4000, 3000, True, 0, "PNG", False)
    return DecodedItem(
        item=item,
        source=Path("a.png"),
        owned=False,
        stem="s",
        plan=plan,
        temp_thumbnails={},
        thumbnail_key="k",
        clip_source=Path("k"),
        width=4000,
        height=3000,
        file_size=1,
        source_hash="h",
        pixel_hash=None,
        phash=None,
        colors=[],
    )


def test_finish_reserves_grid_detection_only_for_maps():
    cfg = PipelineConfig(enable_image_grid_detection=True)
    assert finish_peak_bytes(_decoded("battlemap"), cfg) > 0
    assert finish_peak_bytes(_decoded("scene"), cfg) == 0
    assert finish_peak_bytes(_decoded("battlemap", kind="video"), cfg) == 0


def test_finish_reserves_a_full_decode_for_conversion():
    cfg = PipelineConfig(enable_image_grid_detection=False, stored_format=StoredFormat("webp"))
    assert finish_peak_bytes(_decoded("scene"), cfg) == 4000 * 3000 * 5
