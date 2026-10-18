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
from datetime import timedelta
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
    assert detail["groups"][0]["counts"]["sorted_out"] == 3
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


def test_a_head_for_other_embeddings_is_not_used(auto, monkeypatch, caplog):
    head = _head()
    head.embedding_dim = 512
    monkeypatch.setattr(ingest_process, "active_head", lambda: head)
    monkeypatch.setattr(ingest_process, "_mismatch_logged", set())
    job_id = import_files(auto, {"A/Pack/goblin.png": solid("blue")})
    auto.worker.drain()
    assert rows(auto, job_id)["A/Pack/goblin.png"].state == "done"
    import_files(auto, {"B/Pack/goblin.png": solid("blue", size=(40, 40))})
    auto.worker.drain()
    warnings = [r for r in caplog.records if "Image-type head expects" in r.getMessage()]
    assert len(warnings) == 1  # once per encoder, not every batch


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


def test_dismissing_an_import_expires_what_auto_sorted_out(auto):
    job_id = import_files(
        auto, {"A/Keep/map.png": solid("red"), "A/Keep/goblin.png": solid("blue")}
    )
    auto.worker.drain()
    goblin = rows(auto, job_id)["A/Keep/goblin.png"]
    group_id = image_for(auto, rows(auto, job_id)["A/Keep/map.png"]).group_id
    staged = ingest_queue.staged_path(job_id, goblin.staging_key)
    preview = ingest_queue.staged_path(job_id, goblin.preview_key)

    assert auto.client.post(f"{BASE}/{job_id}/dismiss").status_code == 200
    goblin = rows(auto, job_id)["A/Keep/goblin.png"]
    assert (goblin.state, goblin.error_kind) == ("skipped", ingest_queue.KIND_SORTED_OUT_EXPIRED)
    assert goblin.error_reason == "Looks like a token"  # the report still says why
    assert goblin.staging_key is None and goblin.preview_key is None
    assert not staged.exists() and not preview.exists()
    assert auto.detail(job_id)["counts"]["sorted_out"] == 0

    # No longer in the group editor, and can't be included
    assert auto.client.get(f"{BASE}/sorted-out/counts").json()["counts"] == {}
    listed = auto.client.get(f"{BASE}/sorted-out", params={"image_group_id": group_id}).json()
    assert listed["items"] == []
    assert _include(auto, [goblin.id])["affected"] == 0
    assert rows(auto, job_id)["A/Keep/goblin.png"].state == "skipped"


def test_clear_finished_expires_what_auto_sorted_out(auto):
    job_id = import_files(auto, {"A/Pack/goblin.png": solid("blue")})
    auto.worker.drain()
    preview = ingest_queue.staged_path(job_id, rows(auto, job_id)["A/Pack/goblin.png"].preview_key)
    assert auto.client.post(f"{BASE}/dismiss-finished").json() == {"dismissed": 1}
    assert not preview.exists()
    assert rows(auto, job_id)["A/Pack/goblin.png"].error_kind == (
        ingest_queue.KIND_SORTED_OUT_EXPIRED
    )


def test_maintenance_dismisses_imports_finished_a_day_ago(auto):
    job_id = import_files(auto, {"A/Pack/goblin.png": solid("blue")})
    auto.worker.drain()
    goblin = rows(auto, job_id)["A/Pack/goblin.png"]
    staged = ingest_queue.staged_path(job_id, goblin.staging_key)
    preview = ingest_queue.staged_path(job_id, goblin.preview_key)
    now = ingest_queue.utcnow()

    assert ingest_maintenance.expire_finished_jobs(now=now + timedelta(hours=23)) == 0
    assert staged.is_file() and preview.is_file()
    assert auto.detail(job_id)["dismissed"] is False

    assert ingest_maintenance.expire_finished_jobs(now=now + timedelta(hours=25)) == 1
    assert auto.detail(job_id)["dismissed"] is True
    assert not staged.exists() and not preview.exists()
    assert rows(auto, job_id)["A/Pack/goblin.png"].error_kind == (
        ingest_queue.KIND_SORTED_OUT_EXPIRED
    )


def test_maintenance_expires_imports_dismissed_another_way(auto):
    """E.g. dismissed before expiry existed: their sorted-out items expire too."""
    job_id = import_files(auto, {"A/Pack/goblin.png": solid("blue")})
    auto.worker.drain()
    preview = ingest_queue.staged_path(job_id, rows(auto, job_id)["A/Pack/goblin.png"].preview_key)
    with auto.SessionLocal() as db:
        db.get_one(ImportJob, job_id).dismissed_at = ingest_queue.utcnow()
        db.commit()
    assert ingest_maintenance.expire_finished_jobs() == 0
    assert not preview.exists()


def test_maintenance_never_expires_open_imports(auto):
    job_id = auto.create("Test", image_type="auto")
    result = auto.manifest(
        job_id,
        [
            {"relative_path": "A/Pack/goblin.png", "size": len(solid("blue"))},
            {"relative_path": "A/Pack/later.png", "size": 10},
        ],
    )
    ids = {i["relative_path"]: i["item_id"] for i in result["items"]}
    auto.client.post(f"{BASE}/{job_id}/seal")
    auto.put(job_id, ids["A/Pack/goblin.png"], solid("blue"))
    auto.worker.drain()
    later = ingest_queue.utcnow() + timedelta(days=2)
    assert ingest_maintenance.expire_finished_jobs(now=later) == 0
    goblin = rows(auto, job_id)["A/Pack/goblin.png"]
    assert goblin.error_kind == ingest_queue.KIND_SORTED_OUT
    assert ingest_queue.staged_path(job_id, goblin.preview_key).is_file()


def test_the_list_hides_imports_finished_a_day_ago(auto):
    old = import_files(auto, {"A/Pack/map.png": solid("red")})
    recent = import_files(auto, {"B/Pack/map.png": solid("red", size=(40, 30))})
    unfinished = auto.create("Unfinished", image_type="auto")
    auto.worker.drain()
    with auto.SessionLocal() as db:
        db.get_one(ImportJob, old).completed_at = ingest_queue.utcnow() - timedelta(hours=25)
        db.commit()

    listed = {j["id"] for j in auto.client.get(BASE).json()["jobs"]}
    assert listed == {recent, unfinished}
    everything = auto.client.get(BASE, params={"include_dismissed": True}).json()["jobs"]
    assert old in {j["id"] for j in everything}


def test_include_resumes_a_paused_import(auto):
    job_id = auto.create("Test", image_type="auto")
    result = auto.manifest(
        job_id,
        [
            {"relative_path": "A/Pack/goblin.png", "size": len(solid("blue"))},
            {"relative_path": "A/Pack/later.png", "size": 10},
        ],
    )
    ids = {i["relative_path"]: i["item_id"] for i in result["items"]}
    auto.client.post(f"{BASE}/{job_id}/seal")
    auto.put(job_id, ids["A/Pack/goblin.png"], solid("blue"))
    auto.worker.drain()
    assert auto.client.post(f"{BASE}/{job_id}/pause").json()["status"] == "paused"

    _include(auto, [ids["A/Pack/goblin.png"]])
    assert auto.detail(job_id)["status"] == "active"
    auto.worker.drain()
    assert rows(auto, job_id)["A/Pack/goblin.png"].state == "done"


def test_include_deletes_previews_only_after_the_commit(auto):
    job_id = import_files(auto, {"A/Pack/goblin.png": solid("blue")})
    auto.worker.drain()
    goblin = rows(auto, job_id)["A/Pack/goblin.png"]
    preview = ingest_queue.staged_path(job_id, goblin.preview_key)
    with auto.SessionLocal() as db:
        affected, job_ids, previews = ingest_queue.include_sorted_out(db, [goblin.id])
        assert (affected, job_ids, previews) == (1, {job_id}, [(job_id, goblin.preview_key)])
        assert preview.is_file()
        db.rollback()  # e.g. the commit failed: the item can still be included
    assert rows(auto, job_id)["A/Pack/goblin.png"].preview_key == goblin.preview_key
    assert preview.is_file()


# ---------------------------------------------------------------------------
# Failures leave nothing behind
# ---------------------------------------------------------------------------


def previews(job_id: str) -> list[Path]:
    return list(ingest_queue.staging_dir_for(job_id).glob("preview-*"))


def test_finish_failure_of_an_upload_leaves_no_temp_files(auto, monkeypatch):
    def broken_convert(*_args):
        raise RuntimeError("encoder crashed")

    monkeypatch.setattr(ingest_process, "convert_stored_format", broken_convert)
    job_id = import_files(auto, {"A/Pack/map.png": solid("red")})
    auto.worker.drain()

    item = rows(auto, job_id)["A/Pack/map.png"]
    assert (item.state, item.error_stage, item.attempts) == ("failed", "convert", 3)
    assert ingest_queue.staged_path(job_id, item.staging_key).is_file()  # kept for Retry
    assert incoming_files() == []


def test_finish_after_the_staged_file_vanished_asks_for_it_again(auto, monkeypatch):
    sort = ingest_process.sort_auto_items

    def sort_then_lose_bytes(decoded):
        result = sort(decoded)
        for d in decoded:
            d.source.unlink()
        return result

    monkeypatch.setattr(ingest_process, "sort_auto_items", sort_then_lose_bytes)
    job_id = import_files(auto, {"A/Pack/map.png": solid("red")})
    auto.worker.drain()

    item = rows(auto, job_id)["A/Pack/map.png"]
    assert (item.state, item.error_kind) == ("awaiting_bytes", ingest_queue.KIND_BYTES_LOST)
    assert item.staging_key is None
    assert incoming_files() == []


@pytest.mark.parametrize("failure", ["grid_detection", "convert"])
def test_finish_failure_of_a_local_file_leaves_no_temp_files(auto, tmp_path, monkeypatch, failure):
    """Local items are finished from our own copy; it, the thumbnails and any converted
    file are deleted when finishing fails."""
    monkeypatch.setattr("backend.app.config.settings.app_mode", "app")
    if failure == "grid_detection":
        auto.worker._config_loader = lambda: PipelineConfig(
            enable_image_grid_detection=True, ingestion_batch_size=8
        )

        def broken_detector(*_args, **_kwargs):
            raise RuntimeError("detector crashed")

        monkeypatch.setattr(
            "backend.pipeline.tasks.grid_detection.detect_grid_from_image", broken_detector
        )
    else:

        def convert(source, dest_dir, stem, _spec):
            out = dest_dir / f"{stem}.webp"
            with PILImage.open(source) as image:
                image.save(out, "WEBP")
            return out

        file_sha256 = ingest_process.file_sha256

        def sha_failing_on_converted(path):
            if path.suffix == ".webp":
                raise RuntimeError("read error")
            return file_sha256(path)

        monkeypatch.setattr(ingest_process, "convert_stored_format", convert)
        monkeypatch.setattr(ingest_process, "file_sha256", sha_failing_on_converted)

    root = tmp_path / "maps"
    (root / "Pack").mkdir(parents=True)
    (root / "Pack" / "map.png").write_bytes(solid("red"))
    job_id = auto.create("Local", image_type="auto")
    r = auto.client.post(f"{BASE}/{job_id}/local-sources", json={"paths": [str(root)]})
    assert r.status_code == 200, r.text
    assert auto.client.post(f"{BASE}/{job_id}/seal").status_code == 200
    auto.worker.drain()

    (item,) = rows(auto, job_id).values()
    assert (item.state, item.error_stage) == ("failed", failure)
    assert incoming_files() == []
    assert (root / "Pack" / "map.png").read_bytes() == solid("red")


def test_embedding_failure_with_auto_items_leaves_no_temp_files(auto, monkeypatch):
    def broken_embed(paths, **_kw):
        raise RuntimeError("model crashed")

    monkeypatch.setattr(
        "backend.pipeline.tasks.embedding_generation.batch_generate_clip_embeddings",
        broken_embed,
    )
    job_id = import_files(auto, {"A/Pack/map.png": solid("red"), "A/Pack/gob.png": solid("blue")})
    auto.worker.drain()

    items = rows(auto, job_id).values()
    assert {(i.state, i.error_stage, i.attempts) for i in items} == {("failed", "embedding", 3)}
    assert incoming_files() == [] and previews(job_id) == []

    monkeypatch.setattr(
        "backend.pipeline.tasks.embedding_generation.batch_generate_clip_embeddings", _embed
    )
    assert auto.client.post(f"{BASE}/{job_id}/retry").json()["affected"] == 2
    auto.worker.drain()
    states = {p: i.state for p, i in rows(auto, job_id).items()}
    assert states == {"A/Pack/map.png": "done", "A/Pack/gob.png": "skipped"}


@pytest.mark.parametrize("failure", ["classify", "record"])
def test_sort_failure_fails_the_auto_items_and_leaves_nothing_behind(auto, monkeypatch, failure):
    """Whether the head breaks or recording the verdicts does (after previews were moved),
    the batch's Auto items fail and the queue carries on."""
    if failure == "classify":
        head = _head()

        def broken_classify(*_args, **_kwargs):
            raise RuntimeError("head crashed")

        monkeypatch.setattr(head, "classify", broken_classify)
        monkeypatch.setattr(ingest_process, "active_head", lambda: head)
    else:

        def broken_record(_sorted_out):
            raise RuntimeError("database is locked")

        monkeypatch.setattr(ingest_process, "record_sorted_out", broken_record)

    job_id = import_files(auto, {"A/Pack/map.png": solid("red"), "A/Pack/gob.png": solid("blue")})
    auto.worker.drain()

    items = rows(auto, job_id).values()
    assert {(i.state, i.error_stage) for i in items} == {("failed", "classify")}
    assert all(i.preview_key is None for i in items)
    assert incoming_files() == [] and previews(job_id) == []

    monkeypatch.undo()
    monkeypatch.setattr(
        "backend.pipeline.tasks.embedding_generation.batch_generate_clip_embeddings", _embed
    )
    head = _head()
    monkeypatch.setattr(ingest_process, "active_head", lambda: head)
    auto.client.post(f"{BASE}/{job_id}/retry")
    auto.worker.drain()
    states = {p: i.state for p, i in rows(auto, job_id).items()}
    assert states == {"A/Pack/map.png": "done", "A/Pack/gob.png": "skipped"}


def test_a_sorted_out_item_no_longer_processing_loses_its_preview(auto):
    job_id = import_files(auto, {"A/Pack/map.png": solid("red")})
    auto.worker.drain()
    item = rows(auto, job_id)["A/Pack/map.png"]  # done, e.g. by a concurrent batch
    preview = ingest_queue.staging_dir_for(job_id) / "preview-late.jpg"
    preview.write_bytes(b"x")

    ingest_queue.record_sorted_out(
        [ingest_queue.SortedOut(item.id, "Looks like a token", {}, preview.name)]
    )
    assert not preview.exists()
    assert rows(auto, job_id)["A/Pack/map.png"].state == "done"


def test_auto_video_is_classified_from_its_first_frame(auto, tmp_path):
    import cv2
    import numpy as np

    path = tmp_path / "clip.mp4"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter.fourcc(*"mp4v"), 5, (64, 48))
    for _ in range(3):
        writer.write(np.full((48, 64, 3), COLOURS["red"][::-1], np.uint8))  # BGR
    writer.release()

    job_id = import_files(auto, {"A/Pack/clip.mp4": path.read_bytes()})
    auto.worker.drain()

    item = rows(auto, job_id)["A/Pack/clip.mp4"]
    assert item.state == "done", item.error_detail
    assert json.loads(item.classification)["group"] == "map"
    image = image_for(auto, item)
    assert (image.media_type, image.image_type) == ("video", "battlemap")
    assert incoming_files() == []


# ---------------------------------------------------------------------------
# Review: which gallery groups the editor can open
# ---------------------------------------------------------------------------


def test_reviewable_groups_wait_for_every_import_group_that_feeds_them(auto):
    """Two import groups resolving to one gallery group: it is reviewable only once both
    are finished, and counted once."""
    from backend.app.models import ImageGroup, ImportGroup

    files = {
        "A/One/a.png": solid("red", size=(60, 40)),
        "A/Two/b.png": solid("red", size=(61, 40)),
        "A/Three/c.png": solid("red", size=(62, 40)),
    }
    job_id = auto.create("Test", image_type="auto")
    result = auto.manifest(job_id, [{"relative_path": p, "size": len(d)} for p, d in files.items()])
    ids = {i["relative_path"]: i["item_id"] for i in result["items"]}
    auto.client.post(f"{BASE}/{job_id}/seal")
    with auto.SessionLocal() as db:
        shared = ImageGroup(base_name="Shared", author="A")
        db.add(shared)
        db.flush()
        shared_id = shared.id
        for group in db.query(ImportGroup).filter_by(job_id=job_id):
            if group.group_name in ("One", "Two"):
                group.image_group_id = shared_id
                group.merged_into_existing = True
        db.commit()

    for path in ("A/One/a.png", "A/Three/c.png"):
        auto.put(job_id, ids[path], files[path])
    auto.worker.drain()
    detail = auto.detail(job_id)
    three = next(g for g in detail["groups"] if g["group_name"] == "Three")
    assert detail["reviewable_group_ids"] == [three["image_group_id"]]  # Two is still open
    assert detail["groups_reviewable"] == 1

    auto.put(job_id, ids["A/Two/b.png"], files["A/Two/b.png"])
    auto.worker.drain()
    detail = auto.detail(job_id)
    order = {g["image_group_id"]: g["sort_order"] for g in reversed(detail["groups"])}
    assert detail["reviewable_group_ids"] == sorted(
        {shared_id, three["image_group_id"]}, key=order.get
    )
    assert detail["groups_reviewable"] == 2
    summary = next(j for j in auto.client.get(BASE).json()["jobs"] if j["id"] == job_id)
    assert summary["groups_reviewable"] == 2


def test_a_group_with_only_sorted_out_items_is_not_reviewable(auto):
    job_id = import_files(auto, {"A/Keep/map.png": solid("red"), "A/Cave/orc.png": solid("blue")})
    auto.worker.drain()
    detail = auto.detail(job_id)
    keep = next(g for g in detail["groups"] if g["group_name"] == "Keep")
    cave = next(g for g in detail["groups"] if g["group_name"] == "Cave")
    assert detail["reviewable_group_ids"] == [keep["image_group_id"]]
    assert (keep["counts"]["sorted_out"], cave["counts"]["sorted_out"]) == (0, 1)
