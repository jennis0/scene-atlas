"""Integration tests for Auto image type on import (ADR-020, design/ingestion.md §5.6).

Drives the real imports API and worker. The embedding model is faked so that each
test image's colour picks its embedding, and a real ``ImageTypeHead`` (built from a
small dict) turns that into a verdict: red → map, green → illustration, blue → token,
black → other, white → unsure (falls back to other), magenta → token, but with
illustration rated above map.
"""

from __future__ import annotations

import io
import json
import os
import time
from pathlib import Path

import pytest
from PIL import Image as PILImage

from backend.app.models import Image, ImportItem, ImportJob
from backend.app.services import get_image_store, get_thumbnail_store
from backend.app.services.image_type_classifier import ImageTypeHead
from backend.pipeline import ingest_maintenance, ingest_process, ingest_queue
from backend.pipeline.pipeline_config import PipelineConfig

from .test_imports_api import BASE

DIM = 8
COLOURS = {
    "red": (220, 30, 30),
    "green": (30, 200, 40),
    "blue": (30, 40, 220),
    "black": (5, 5, 5),
    "white": (250, 250, 250),
    "magenta": (230, 20, 230),
}
# One embedding per colour; the head's weight is 10x identity on the first four dims
EMBEDDINGS = {
    "red": [1, 0, 0, 0],
    "green": [0, 1, 0, 0],
    "blue": [0, 0, 1, 0],
    "black": [0, 0, 0, 1],
    "white": [1, 1, 1, 1],  # all four equal: 0.25 each, below min_confidence
    "magenta": [0.2, 0.5, 1, 0],
}


def _head() -> ImageTypeHead:
    classes = ["map", "illustration", "token", "other"]
    weight = [[10.0 if c == i else 0.0 for c in range(DIM)] for i in range(len(classes))]
    return ImageTypeHead(
        {
            "format": "scene-atlas-linear-head/2",
            "encoder_sha256": "test",
            "encoder_version": "test-encoder",
            "embedding_dim": DIM,
            "classes": classes,
            "groups": {c: [c] for c in classes},
            "weight": weight,
            "bias": [0.0] * len(classes),
            "fallback": {"group": "other", "min_confidence": 0.5},
        }
    )


def _colour_of(path: str) -> str:
    with PILImage.open(path) as img:
        r, g, b = img.convert("RGB").resize((1, 1)).getpixel((0, 0))
    return min(
        COLOURS, key=lambda c: sum((x - y) ** 2 for x, y in zip(COLOURS[c], (r, g, b), strict=True))
    )


def _embed(paths, **_kw):
    return [[*EMBEDDINGS[_colour_of(p)], 0, 0, 0, 0][:DIM] for p in paths]


@pytest.fixture
def auto(api, monkeypatch):
    monkeypatch.setattr(
        "backend.pipeline.tasks.embedding_generation.batch_generate_clip_embeddings", _embed
    )
    head = _head()
    monkeypatch.setattr(ingest_process, "active_head", lambda: head)
    return api


def solid(colour: str, size=(64, 48), fmt="PNG") -> bytes:
    """A solid image; sizes keep same-coloured images from being pixel duplicates."""
    buf = io.BytesIO()
    PILImage.new("RGB", size, COLOURS[colour]).save(buf, format=fmt)
    return buf.getvalue()


def import_files(api, files: dict[str, bytes], image_type="auto") -> str:
    job_id = api.create("Test", image_type=image_type)
    result = api.manifest(
        job_id, [{"relative_path": p, "size": len(d), "client_ref": p} for p, d in files.items()]
    )
    ids = {i["relative_path"]: i["item_id"] for i in result["items"]}
    assert api.client.post(f"{BASE}/{job_id}/seal").status_code == 200
    for path, data in files.items():
        assert api.put(job_id, ids[path], data).status_code == 200
    return job_id


def rows(api, job_id) -> dict[str, ImportItem]:
    with api.SessionLocal() as db:
        found = db.query(ImportItem).filter_by(job_id=job_id).all()
        for row in found:
            db.expunge(row)
        return {row.relative_path: row for row in found}


def image_for(api, item: ImportItem) -> Image:
    with api.SessionLocal() as db:
        image = db.get(Image, item.image_id)
        db.expunge(image)
        return image


def incoming_files() -> list[Path]:
    return [
        p
        for store in (get_image_store(), get_thumbnail_store())
        for p in (store.base_dir / ".incoming").glob("*")
    ]


# ---------------------------------------------------------------------------
# Sorting
# ---------------------------------------------------------------------------


def test_auto_sorts_each_image(auto):
    job_id = import_files(
        auto,
        {
            "A/Pack/map.png": solid("red"),
            "A/Pack/vista.png": solid("green"),
            "A/Pack/goblin.png": solid("blue"),
            "A/Pack/sword.png": solid("black"),
            "A/Pack/blank.png": solid("white"),
        },
    )
    auto.worker.drain()

    items = rows(auto, job_id)
    assert image_for(auto, items["A/Pack/map.png"]).image_type == "battlemap"
    assert image_for(auto, items["A/Pack/vista.png"]).image_type == "scene"
    assert json.loads(items["A/Pack/map.png"].classification)["group"] == "map"

    reasons = {
        "A/Pack/goblin.png": "Looks like a token",
        "A/Pack/sword.png": "Doesn't look like a map or a scene",
        "A/Pack/blank.png": "Couldn't tell whether this is a map or a scene",
    }
    for path, reason in reasons.items():
        item = items[path]
        assert (item.state, item.error_kind, item.error_reason) == (
            "skipped",
            ingest_queue.KIND_SORTED_OUT,
            reason,
        )
        assert item.image_id is None
        # Bytes and a preview are kept so the user can check it and include it
        assert ingest_queue.staged_path(job_id, item.staging_key).is_file()
        assert ingest_queue.staged_path(job_id, item.preview_key).is_file()
    assert json.loads(items["A/Pack/blank.png"].classification)["fell_back"] is True

    detail = auto.detail(job_id)
    assert detail["status"] == "completed"
    assert detail["counts"]["done"] == 2 and detail["counts"]["skipped"] == 3
    assert detail["counts"]["sorted_out"] == 3
    assert detail["groups"][0]["counts"]["sorted_out"] == 0  # job counts only
    with auto.SessionLocal() as db:
        assert db.query(Image).count() == 2
    assert incoming_files() == []


def test_fixed_types_are_never_sorted(auto):
    job_id = import_files(auto, {"A/Tokens/goblin.png": solid("blue")}, image_type="scene")
    auto.worker.drain()
    item = rows(auto, job_id)["A/Tokens/goblin.png"]
    assert item.state == "done" and item.classification is None
    assert image_for(auto, item).image_type == "scene"


def test_without_a_head_auto_imports_battlemaps(auto, monkeypatch):
    monkeypatch.setattr(ingest_process, "active_head", lambda: None)
    job_id = import_files(auto, {"A/Pack/goblin.png": solid("blue")})
    auto.worker.drain()
    item = rows(auto, job_id)["A/Pack/goblin.png"]
    assert item.state == "done" and item.classification is None
    assert image_for(auto, item).image_type == "battlemap"


def test_a_head_for_other_embeddings_is_not_used(auto, monkeypatch):
    head = _head()
    head.embedding_dim = 512
    monkeypatch.setattr(ingest_process, "active_head", lambda: head)
    job_id = import_files(auto, {"A/Pack/goblin.png": solid("blue")})
    auto.worker.drain()
    assert rows(auto, job_id)["A/Pack/goblin.png"].state == "done"


def test_scene_takes_the_scene_parse(auto):
    """Auto items are grouped as battlemaps at seal; a scene drops the file name's grid."""
    job_id = import_files(
        auto,
        {
            "A/Keep/Keep_Gridded_20x30.png": solid("red"),
            "A/Keep/Keep_Gridded_30x20.png": solid("green"),
        },
    )
    auto.worker.drain()
    items = rows(auto, job_id)
    assert "scene_tags" in json.loads(items["A/Keep/Keep_Gridded_20x30.png"].parsed)
    as_map = image_for(auto, items["A/Keep/Keep_Gridded_20x30.png"])
    as_scene = image_for(auto, items["A/Keep/Keep_Gridded_30x20.png"])
    assert (as_map.gridded, as_map.grid_width, as_map.grid_height) == (True, 20, 30)
    assert (as_scene.gridded, as_scene.grid_width, as_scene.grid_height) == (None, None, None)
    assert as_map.group_id == as_scene.group_id  # one group, as before


def test_grid_detection_runs_only_for_maps(auto, monkeypatch):
    seen: list[tuple[int, int]] = []

    def detect(path, width, height, **_kw):
        seen.append((width, height))
        return

    monkeypatch.setattr("backend.pipeline.tasks.grid_detection.detect_grid_from_image", detect)
    auto.worker._config_loader = lambda: PipelineConfig(
        enable_image_grid_detection=True, ingestion_batch_size=8
    )
    import_files(
        auto,
        {
            "A/Pack/map.png": solid("red", size=(70, 50)),
            "A/Pack/vista.png": solid("green", size=(60, 40)),
            "A/Pack/goblin.png": solid("blue", size=(50, 50)),
        },
    )
    auto.worker.drain()
    assert seen == [(70, 50)]


def test_local_auto_import_leaves_no_temp_files(auto, tmp_path, monkeypatch):
    monkeypatch.setattr("backend.app.config.settings.app_mode", "app")
    root = tmp_path / "maps"
    (root / "Pack").mkdir(parents=True)
    (root / "Pack" / "map.png").write_bytes(solid("red"))
    (root / "Pack" / "goblin.png").write_bytes(solid("blue"))
    job_id = auto.create("Local", image_type="auto")
    r = auto.client.post(f"{BASE}/{job_id}/local-sources", json={"paths": [str(root)]})
    assert r.status_code == 200, r.text
    assert auto.client.post(f"{BASE}/{job_id}/seal").status_code == 200
    auto.worker.drain()

    items = {Path(p).name: item for p, item in rows(auto, job_id).items()}
    assert items["map.png"].state == "done"
    goblin = items["goblin.png"]
    assert goblin.error_kind == ingest_queue.KIND_SORTED_OUT
    assert ingest_queue.staged_path(job_id, goblin.preview_key).is_file()
    assert incoming_files() == []
    assert (root / "Pack" / "goblin.png").read_bytes() == solid("blue")  # never touched


# ---------------------------------------------------------------------------
# Including sorted-out items
# ---------------------------------------------------------------------------


def _include(api, item_ids) -> dict:
    r = api.client.post(f"{BASE}/include", json={"item_ids": item_ids})
    assert r.status_code == 200, r.text
    return r.json()


def test_include_imports_with_the_likelier_type(auto):
    job_id = import_files(
        auto,
        {"A/Pack/goblin.png": solid("blue"), "A/Pack/portrait.png": solid("magenta")},
    )
    auto.worker.drain()
    items = rows(auto, job_id)
    goblin, portrait = items["A/Pack/goblin.png"], items["A/Pack/portrait.png"]
    preview = ingest_queue.staged_path(job_id, goblin.preview_key)

    result = _include(auto, [goblin.id, portrait.id])
    assert result == {"affected": 2, "job_ids": [job_id]}
    assert not preview.exists()
    assert auto.detail(job_id)["status"] == "active"
    auto.worker.drain()

    items = rows(auto, job_id)
    assert {i.state for i in items.values()} == {"done"}
    assert image_for(auto, items["A/Pack/goblin.png"]).image_type == "battlemap"
    assert image_for(auto, items["A/Pack/portrait.png"]).image_type == "scene"
    assert items["A/Pack/goblin.png"].preview_key is None


def test_include_reopens_a_dismissed_or_cancelled_import(auto):
    job_id = import_files(auto, {"A/Pack/goblin.png": solid("blue")})
    auto.worker.drain()
    with auto.SessionLocal() as db:
        job = db.get(ImportJob, job_id)
        job.status = "cancelled"
        job.dismissed_at = ingest_queue.utcnow()
        db.commit()
    _include(auto, [rows(auto, job_id)["A/Pack/goblin.png"].id])
    detail = auto.detail(job_id)
    assert detail["status"] == "active" and detail["dismissed"] is False
    auto.worker.drain()
    assert auto.detail(job_id)["counts"]["done"] == 1


def test_include_ignores_other_skips(auto):
    job_id = auto.create("Test", image_type="auto")
    auto.manifest(job_id, [{"relative_path": "A/G/a.png", "size": 10}])
    auto.client.post(f"{BASE}/{job_id}/seal")
    auto.client.post(f"{BASE}/{job_id}/cancel")
    item = rows(auto, job_id)["A/G/a.png"]
    assert item.state == "skipped"
    assert _include(auto, [item.id])["affected"] == 0
    assert rows(auto, job_id)["A/G/a.png"].state == "skipped"


def test_include_without_staged_bytes_asks_for_them_again(auto):
    job_id = import_files(auto, {"A/Pack/goblin.png": solid("blue")})
    auto.worker.drain()
    goblin = rows(auto, job_id)["A/Pack/goblin.png"]
    ingest_queue.staged_path(job_id, goblin.staging_key).unlink()
    _include(auto, [goblin.id])
    assert rows(auto, job_id)["A/Pack/goblin.png"].state == "awaiting_bytes"


# ---------------------------------------------------------------------------
# Group editor API
# ---------------------------------------------------------------------------


def test_sorted_out_items_are_listed_by_gallery_group(auto):
    job_id = import_files(
        auto,
        {
            "A/Keep/map.png": solid("red"),
            "A/Keep/goblin.png": solid("blue"),
            "A/Keep/sword.png": solid("black"),
            "A/Tokens/orc.png": solid("blue", size=(40, 40)),  # no image: no gallery group
        },
    )
    auto.worker.drain()
    items = rows(auto, job_id)
    group_id = image_for(auto, items["A/Keep/map.png"]).group_id

    counts = auto.client.get(f"{BASE}/sorted-out/counts").json()["counts"]
    assert counts == {str(group_id): 2}

    listed = auto.client.get(f"{BASE}/sorted-out", params={"image_group_id": group_id}).json()
    assert listed["truncated"] is False
    by_path = {i["relative_path"]: i for i in listed["items"]}
    assert set(by_path) == {"A/Keep/goblin.png", "A/Keep/sword.png"}
    goblin = by_path["A/Keep/goblin.png"]
    assert goblin["job_id"] == job_id and goblin["has_preview"] is True
    assert goblin["error_reason"] == "Looks like a token"
    assert goblin["classification"]["group"] == "token"
    assert "preview_key" not in goblin

    preview = auto.client.get(f"{BASE}/{job_id}/items/{goblin['id']}/preview")
    assert preview.status_code == 200
    assert PILImage.open(io.BytesIO(preview.content)).size[0] > 0


def test_preview_is_scoped_to_its_import(auto):
    job_id = import_files(auto, {"A/Pack/goblin.png": solid("blue")})
    other_job = import_files(auto, {"A/Pack/map.png": solid("red")})
    auto.worker.drain()
    goblin = rows(auto, job_id)["A/Pack/goblin.png"]
    map_item = rows(auto, other_job)["A/Pack/map.png"]
    assert auto.client.get(f"{BASE}/{other_job}/items/{goblin.id}/preview").status_code == 404
    assert auto.client.get(f"{BASE}/{other_job}/items/{map_item.id}/preview").status_code == 404


# ---------------------------------------------------------------------------
# Maintenance
# ---------------------------------------------------------------------------


def test_maintenance_keeps_sorted_out_bytes_and_previews(auto):
    job_id = import_files(auto, {"A/Pack/goblin.png": solid("blue")})
    auto.worker.drain()
    goblin = rows(auto, job_id)["A/Pack/goblin.png"]
    staged = ingest_queue.staged_path(job_id, goblin.staging_key)
    preview = ingest_queue.staged_path(job_id, goblin.preview_key)
    old = time.time() - 10 * 24 * 3600
    for path in (staged, preview):
        os.utime(path, (old, old))

    assert ingest_maintenance.release_staged_bytes() == 0
    assert ingest_maintenance.sweep_stray_staging_files() == 0
    assert staged.is_file() and preview.is_file()
