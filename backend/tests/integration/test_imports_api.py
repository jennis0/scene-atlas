"""Integration tests for the imports API (ADR-018, design/ingest-redesign.md §7).

Drives the real HTTP API with the TestClient, and the ingest worker
synchronously with ``drain()``. Embeddings and LanceDB are faked.
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import timedelta

import numpy as np
import pytest
from PIL import Image as PILImage

from backend.app.models import AppSetting, Image, ImageGroup, ImportJob
from backend.app.services import ingest_state as st
from backend.pipeline import ingest_process, ingest_queue, ingest_worker
from backend.pipeline.ingest_worker import IngestWorker
from backend.pipeline.pipeline_config import PipelineConfig

BASE = "/api/v1/imports"


class FakeVectors:
    def __init__(self):
        self.rows = {}

    def batch_add_embeddings(self, items):
        for item in items:
            self.rows[item["image_id"]] = item["embedding"]
        return True

    def get_all_ids(self):
        return set(self.rows)

    def delete_embeddings(self, ids):
        for i in ids:
            self.rows.pop(i, None)
        return True


@pytest.fixture
def api(test_client, tmp_db, monkeypatch):
    engine, SessionLocal = tmp_db
    vectors = FakeVectors()
    monkeypatch.setattr(ingest_process, "get_lancedb_service", lambda: vectors)
    monkeypatch.setattr("backend.app.services.lancedb_service.get_lancedb_service", lambda: vectors)
    monkeypatch.setattr(
        "backend.pipeline.tasks.embedding_generation.batch_generate_clip_embeddings",
        lambda paths, **kw: [[0.1] * 8 for _ in paths],
    )
    monkeypatch.setattr(st, "retry_delay", lambda attempts: timedelta(0))
    worker = IngestWorker(
        config_loader=lambda: PipelineConfig(
            enable_image_grid_detection=False, ingestion_batch_size=8
        ),
        probe=lambda: None,
        probe_interval=0.0,
    )
    monkeypatch.setattr(ingest_worker, "_worker", worker)

    class Api:
        client = test_client

        def __init__(self):
            self.SessionLocal = SessionLocal
            self.worker = worker
            self.vectors = vectors

        def create(self, label="Test", image_type="battlemap"):
            r = self.client.post(BASE, json={"label": label, "default_image_type": image_type})
            assert r.status_code == 201, r.text
            return r.json()["id"]

        def manifest(self, job_id, files):
            r = self.client.post(f"{BASE}/{job_id}/manifest", json={"files": files})
            assert r.status_code == 200, r.text
            return r.json()

        def put(self, job_id, item_id, data: bytes):
            return self.client.put(f"{BASE}/{job_id}/items/{item_id}/content", content=data)

        def detail(self, job_id):
            r = self.client.get(f"{BASE}/{job_id}")
            assert r.status_code == 200, r.text
            return r.json()

        def set_app_setting(self, key, value):
            with self.SessionLocal() as db:
                row = db.query(AppSetting).filter_by(key=key).one()
                row.value_json = json.dumps(value)
                db.commit()

    return Api()


def image_bytes(seed=0, fmt="PNG", size=(64, 48)) -> bytes:
    pixels = np.random.default_rng(seed).integers(0, 255, (size[1], size[0], 3), dtype=np.uint8)
    buf = io.BytesIO()
    PILImage.fromarray(pixels).save(buf, format=fmt)
    return buf.getvalue()


def import_files(api, files: dict[str, bytes], label="Test") -> tuple[str, dict[str, int]]:
    """Create, manifest, seal and upload; returns (job_id, path → item_id)."""
    job_id = api.create(label)
    result = api.manifest(
        job_id, [{"relative_path": p, "size": len(d), "client_ref": p} for p, d in files.items()]
    )
    ids = {i["relative_path"]: i["item_id"] for i in result["items"]}
    assert api.client.post(f"{BASE}/{job_id}/seal").status_code == 200
    for path, data in files.items():
        if path in ids:
            assert api.put(job_id, ids[path], data).status_code == 200
    return job_id, ids


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_full_flow(api):
    job_id = api.create("Forest Pack")
    result = api.manifest(
        job_id,
        [
            {"relative_path": "Czepeku/Forest/Forest_Day.png", "size": 10, "client_ref": "a"},
            {"relative_path": "Czepeku/Forest/Forest_Night.png", "size": 10, "client_ref": "b"},
            {"relative_path": "Czepeku/Forest/._Forest_Day.png", "size": 4},
            {"relative_path": "Czepeku/Forest/readme.txt", "size": 4, "client_ref": "c"},
        ],
    )
    assert result["ignored"] == 1  # AppleDouble junk
    by_ref = {i["client_ref"]: i for i in result["items"]}
    assert by_ref["c"]["state"] == "skipped"
    assert by_ref["a"]["state"] == by_ref["b"]["state"] == "awaiting_bytes"

    detail = api.client.post(f"{BASE}/{job_id}/seal").json()
    assert detail["planned"] is True
    assert [g["group_name"] for g in detail["groups"]] == ["Forest"]

    for ref, seed in (("a", 1), ("b", 2)):
        r = api.put(job_id, by_ref[ref]["item_id"], image_bytes(seed))
        assert r.status_code == 200 and r.json()["state"] == "ready"

    assert api.detail(job_id)["status"] == "active"
    api.worker.drain()

    detail = api.detail(job_id)
    assert detail["status"] == "completed"
    assert detail["counts"]["done"] == 2 and detail["counts"]["skipped"] == 1
    assert detail["groups"][0]["counts"]["done"] == 2
    assert detail["groups"][0]["image_group_id"] is not None
    with api.SessionLocal() as db:
        assert db.query(Image).count() == 2


def test_list_supports_etag(api):
    api.create()
    first = api.client.get(BASE)
    assert first.status_code == 200
    etag = first.headers["etag"]
    assert len(first.json()["jobs"]) == 1
    again = api.client.get(BASE, headers={"If-None-Match": etag})
    assert again.status_code == 304
    api.create("Another")  # any change bumps the version
    assert api.client.get(BASE, headers={"If-None-Match": etag}).status_code == 200


def test_items_are_paginated(api):
    job_id = api.create()
    api.manifest(job_id, [{"relative_path": f"A/G/{n}.png", "size": 1} for n in range(5)])
    page = api.client.get(f"{BASE}/{job_id}/items", params={"limit": 2}).json()
    assert len(page["items"]) == 2 and page["next_after"] is not None
    rest = api.client.get(
        f"{BASE}/{job_id}/items", params={"limit": 10, "after": page["next_after"]}
    ).json()
    assert len(rest["items"]) == 3 and rest["next_after"] is None
    filtered = api.client.get(f"{BASE}/{job_id}/items", params={"state": "done"}).json()
    assert filtered["items"] == []


def test_unknown_job_is_404(api):
    assert api.client.get(f"{BASE}/nope").status_code == 404
    assert api.client.post(f"{BASE}/nope/seal").status_code == 404


# ---------------------------------------------------------------------------
# Manifest and seal
# ---------------------------------------------------------------------------


def test_manifest_ignores_repeated_paths(api):
    job_id = api.create()
    api.manifest(job_id, [{"relative_path": "A/G/x.png"}])
    again = api.manifest(job_id, [{"relative_path": "A/G/x.png"}, {"relative_path": "A/G/y.png"}])
    assert again["ignored"] == 1
    assert [i["relative_path"] for i in again["items"]] == ["A/G/y.png"]


def test_manifest_after_seal_is_rejected(api):
    job_id = api.create()
    api.manifest(job_id, [{"relative_path": "A/G/x.png"}])
    api.client.post(f"{BASE}/{job_id}/seal")
    r = api.client.post(f"{BASE}/{job_id}/manifest", json={"files": [{"relative_path": "z.png"}]})
    assert r.status_code == 409


def test_manifest_enforces_item_limit(api, monkeypatch):
    monkeypatch.setattr("backend.app.config.settings.max_import_items", 2)
    job_id = api.create()
    files = [{"relative_path": f"A/G/{n}.png"} for n in range(3)]
    r = api.client.post(f"{BASE}/{job_id}/manifest", json={"files": files})
    assert r.status_code == 413


def test_manifest_marks_oversized_files_failed(api):
    api.set_app_setting("max_import_file_size", 100)
    job_id = api.create()
    result = api.manifest(job_id, [{"relative_path": "A/G/big.png", "size": 1000}])
    assert result["items"][0]["state"] == "failed"


def test_seal_is_idempotent(api):
    job_id = api.create()
    api.manifest(job_id, [{"relative_path": "A/G/x.png"}])
    first = api.client.post(f"{BASE}/{job_id}/seal").json()
    second = api.client.post(f"{BASE}/{job_id}/seal").json()
    assert first["groups"] == second["groups"]


def test_seal_refuses_when_disk_is_too_full(api, monkeypatch):
    from collections import namedtuple

    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(
        "backend.app.api.imports.shutil.disk_usage", lambda path: usage(10, 10, 1024)
    )
    job_id = api.create()
    api.manifest(job_id, [{"relative_path": "A/G/x.png", "size": 10_000_000}])
    r = api.client.post(f"{BASE}/{job_id}/seal")
    assert r.status_code == 507
    assert "Not enough free disk space" in r.json()["detail"]
    assert api.detail(job_id)["planned"] is False


# ---------------------------------------------------------------------------
# Bytes
# ---------------------------------------------------------------------------


def test_upload_is_idempotent(api):
    job_id, ids = import_files(api, {"A/G/x.png": image_bytes(3)})
    again = api.put(job_id, ids["A/G/x.png"], image_bytes(3))
    assert again.status_code == 200 and again.json()["state"] == "ready"
    api.worker.drain()
    after_done = api.put(job_id, ids["A/G/x.png"], image_bytes(3))
    assert after_done.json()["state"] == "done"
    with api.SessionLocal() as db:
        assert db.query(Image).count() == 1


def test_upload_rejects_mismatched_content(api):
    job_id = api.create()
    (item,) = api.manifest(job_id, [{"relative_path": "A/G/x.png"}])["items"]
    r = api.put(job_id, item["item_id"], b"definitely not a png")
    assert r.status_code == 200
    assert r.json()["state"] == "failed"
    assert r.json()["error_reason"] == "File content doesn't match its type"


def test_upload_enforces_size_limit(api):
    api.set_app_setting("max_import_file_size", 100)
    job_id = api.create()
    (item,) = api.manifest(job_id, [{"relative_path": "A/G/x.png"}])["items"]
    r = api.put(job_id, item["item_id"], image_bytes(4))
    assert r.status_code == 413
    detail = api.client.get(f"{BASE}/{job_id}/items").json()["items"][0]
    assert detail["state"] == "awaiting_bytes"  # can be retried
    assert not any(ingest_queue.staging_dir_for(job_id).glob("*"))


def test_upload_to_item_of_another_job_is_404(api):
    first = api.create()
    second = api.create()
    (item,) = api.manifest(first, [{"relative_path": "A/G/x.png"}])["items"]
    assert api.put(second, item["item_id"], image_bytes(5)).status_code == 404


def test_empty_upload_is_rejected(api):
    job_id = api.create()
    (item,) = api.manifest(job_id, [{"relative_path": "A/G/x.png"}])["items"]
    assert api.put(job_id, item["item_id"], b"").status_code == 400


def test_upload_before_seal_is_processed_after_seal(api):
    job_id = api.create()
    (item,) = api.manifest(job_id, [{"relative_path": "A/G/x.png"}])["items"]
    assert api.put(job_id, item["item_id"], image_bytes(6)).json()["state"] == "ready"
    assert api.worker.drain() == 0  # not planned yet
    api.client.post(f"{BASE}/{job_id}/seal")
    api.worker.drain()
    assert api.detail(job_id)["status"] == "completed"


# ---------------------------------------------------------------------------
# Duplicates
# ---------------------------------------------------------------------------


def test_client_hash_skips_known_file(api):
    data = image_bytes(7)
    import_files(api, {"A/G/x.png": data})
    api.worker.drain()

    job_id = api.create()
    (item,) = api.manifest(job_id, [{"relative_path": "B/H/copy.png"}])["items"]
    r = api.client.post(
        f"{BASE}/{job_id}/hashes",
        json={"items": [{"item_id": item["item_id"], "sha256": hashlib.sha256(data).hexdigest()}]},
    )
    result = r.json()["items"][0]
    assert result["state"] == "duplicate" and result["duplicate_of_image_id"] is not None
    # Uploading it anyway is a harmless no-op.
    assert api.put(job_id, item["item_id"], data).json()["state"] == "duplicate"


def test_byte_duplicate_detected_on_upload(api):
    data = image_bytes(8)
    import_files(api, {"A/G/x.png": data})
    api.worker.drain()
    job_id, ids = import_files(api, {"B/H/copy.png": data})
    item = api.client.get(f"{BASE}/{job_id}/items").json()["items"][0]
    assert item["state"] == "duplicate" and item["duplicate_tier"] == "bytes"
    assert api.detail(job_id)["status"] == "completed"


def test_import_as_copy_endpoint(api):
    data = image_bytes(9)
    import_files(api, {"A/G/x.png": data})
    api.worker.drain()
    job_id, _ = import_files(api, {"B/H/copy.png": data})
    r = api.client.post(f"{BASE}/{job_id}/import-as-copy", json={})
    assert r.json() == {"affected": 1, "status": "active"}
    api.worker.drain()
    assert api.detail(job_id)["counts"]["done"] == 1
    with api.SessionLocal() as db:
        assert db.query(Image).count() == 2


# ---------------------------------------------------------------------------
# Archives
# ---------------------------------------------------------------------------


def _zip(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_archive_expands_into_items(api):
    job_id = api.create()
    body = _zip(
        {
            "Pack/Map/a.png": image_bytes(10),
            "Pack/Map/b.jpg": image_bytes(11, fmt="JPEG"),
            "__MACOSX/Pack/Map/._a.png": b"junk",
            "Pack/notes.txt": b"hello",
            "Pack/inner.zip": _zip({"x.png": image_bytes(12)}),
            "Pack/Map/fake.png": b"not an image",
        }
    )
    r = api.client.put(f"{BASE}/{job_id}/archives", params={"name": "Pack.zip"}, content=body)
    assert r.status_code == 200, r.text
    assert r.json() == {"name": "Pack.zip", "created": 2, "skipped": 2, "failed": 1}

    api.client.post(f"{BASE}/{job_id}/seal")
    api.worker.drain()
    detail = api.detail(job_id)
    assert detail["counts"]["done"] == 2
    assert detail["status"] == "completed"


def test_archive_member_paths_that_collide_are_prefixed(api):
    job_id = api.create()
    api.manifest(job_id, [{"relative_path": "Map/a.png"}])
    body = _zip({"Map/a.png": image_bytes(13)})
    api.client.put(f"{BASE}/{job_id}/archives", params={"name": "Second.zip"}, content=body)
    paths = sorted(
        i["relative_path"] for i in api.client.get(f"{BASE}/{job_id}/items").json()["items"]
    )
    assert paths == ["Map/a.png", "Second/Map/a.png"]


def test_corrupt_archive_becomes_failed_item(api):
    job_id = api.create()
    r = api.client.put(f"{BASE}/{job_id}/archives", params={"name": "bad.zip"}, content=b"nope")
    assert r.json()["failed"] == 1
    (item,) = api.client.get(f"{BASE}/{job_id}/items").json()["items"]
    assert (item["kind"], item["state"]) == ("archive", "failed")


def test_archive_after_seal_is_rejected(api):
    job_id = api.create()
    api.client.post(f"{BASE}/{job_id}/seal")
    body = _zip({"a.png": image_bytes(14)})
    r = api.client.put(f"{BASE}/{job_id}/archives", params={"name": "a.zip"}, content=body)
    assert r.status_code == 409


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------


def test_cancel_skips_open_items_and_keeps_done(api):
    job_id = api.create()
    items = api.manifest(job_id, [{"relative_path": "A/G/a.png"}, {"relative_path": "A/G/b.png"}])[
        "items"
    ]
    api.client.post(f"{BASE}/{job_id}/seal")
    api.put(job_id, items[0]["item_id"], image_bytes(16))
    api.worker.drain()
    r = api.client.post(f"{BASE}/{job_id}/cancel")
    assert r.json() == {"affected": 1, "status": "cancelled"}
    detail = api.detail(job_id)
    assert detail["counts"]["done"] == 1 and detail["counts"]["skipped"] == 1
    with api.SessionLocal() as db:
        assert db.query(Image).count() == 1
    # A cancelled job takes no more bytes.
    assert api.put(job_id, items[1]["item_id"], image_bytes(17)).status_code == 409


def test_pause_and_resume(api):
    job_id, _ = import_files(api, {"A/G/a.png": image_bytes(18)})
    assert api.client.post(f"{BASE}/{job_id}/pause").json()["status"] == "paused"
    assert api.worker.drain() == 0
    assert api.client.post(f"{BASE}/{job_id}/resume").json()["status"] == "active"
    api.worker.drain()
    assert api.detail(job_id)["status"] == "completed"


def test_retry_endpoint(api, monkeypatch):
    # Passes the upload-time type check but can't be decoded by the worker.
    monkeypatch.setattr("backend.app.api.imports.verify_media_mime", lambda path, ext: True)
    job_id, _ = import_files(api, {"A/G/bad.png": b"garbage"})
    api.worker.drain()
    detail = api.detail(job_id)
    assert detail["counts"]["failed"] == 1 and detail["status"] == "completed"
    r = api.client.post(f"{BASE}/{job_id}/retry", json={})
    assert r.json() == {"affected": 1, "status": "active"}
    item = api.client.get(f"{BASE}/{job_id}/items").json()["items"][0]
    assert (item["state"], item["error_reason"]) == ("ready", None)


def test_retry_refused_on_cancelled_job(api):
    job_id = api.create()
    api.client.post(f"{BASE}/{job_id}/cancel")
    assert api.client.post(f"{BASE}/{job_id}/retry", json={}).status_code == 409


def test_finish_upload_skips_missing_files(api):
    job_id = api.create()
    api.manifest(job_id, [{"relative_path": "A/G/a.png"}])
    api.client.post(f"{BASE}/{job_id}/seal")
    r = api.client.post(f"{BASE}/{job_id}/finish-upload")
    assert r.json() == {"affected": 1, "status": "completed"}


def test_skip_group(api):
    job_id = api.create()
    api.manifest(job_id, [{"relative_path": "A/One/a.png"}, {"relative_path": "A/Two/b.png"}])
    groups = api.client.post(f"{BASE}/{job_id}/seal").json()["groups"]
    one = next(g for g in groups if g["group_name"] == "One")
    r = api.client.post(f"{BASE}/{job_id}/groups/{one['id']}/skip")
    assert r.json()["affected"] == 1
    assert api.client.post(f"{BASE}/{job_id}/groups/999999/skip").status_code == 404


def test_dismiss_only_when_finished(api):
    job_id = api.create()
    assert api.client.post(f"{BASE}/{job_id}/dismiss").status_code == 409
    api.client.post(f"{BASE}/{job_id}/cancel")
    assert api.client.post(f"{BASE}/{job_id}/dismiss").status_code == 200
    assert job_id not in [j["id"] for j in api.client.get(BASE).json()["jobs"]]
    listed = api.client.get(BASE, params={"include_dismissed": True}).json()["jobs"]
    assert job_id in [j["id"] for j in listed]


def test_undo_deletes_images_files_and_job(api):
    from backend.app.services import get_image_store, get_thumbnail_store

    job_id, _ = import_files(api, {"A/G/a.png": image_bytes(19), "A/G/b.png": image_bytes(20)})
    api.worker.drain()
    with api.SessionLocal() as db:
        keys = [(i.storage_key, i.thumbnail_key) for i in db.query(Image)]
    assert len(keys) == 2

    r = api.client.delete(f"{BASE}/{job_id}")
    assert r.json() == {"affected": 2, "status": "deleted"}
    assert api.client.get(f"{BASE}/{job_id}").status_code == 404
    with api.SessionLocal() as db:
        assert db.query(Image).count() == 0
        assert db.query(ImageGroup).count() == 0  # created by the job, now empty
    for storage_key, thumbnail_key in keys:
        assert not get_image_store().exists(storage_key)
        assert not get_thumbnail_store().exists(thumbnail_key)
    assert api.vectors.rows == {}


def test_undo_keeps_groups_it_merged_into(api):
    with api.SessionLocal() as db:
        db.add(ImageGroup(base_name="G", author="A"))
        db.commit()
    job_id, _ = import_files(api, {"A/G/a.png": image_bytes(21)})
    api.worker.drain()
    api.client.delete(f"{BASE}/{job_id}")
    with api.SessionLocal() as db:
        assert db.query(ImageGroup).count() == 1


def test_undo_waits_for_in_flight_batch(api):
    job_id, _ = import_files(api, {"A/G/a.png": image_bytes(22)})
    ingest_queue.claim_next_batch(None, 10)  # a batch is mid-flight
    r = api.client.delete(f"{BASE}/{job_id}")
    assert r.status_code == 409
    assert api.detail(job_id)["status"] == "cancelled"


# ---------------------------------------------------------------------------
# Derived state, queue, and guards
# ---------------------------------------------------------------------------


def test_upload_interrupted_is_derived(api):
    job_id = api.create()
    api.manifest(job_id, [{"relative_path": "A/G/a.png"}])
    api.client.post(f"{BASE}/{job_id}/seal")
    assert api.detail(job_id)["upload_interrupted"] is False
    with api.SessionLocal() as db:
        job = db.get(ImportJob, job_id)
        job.created_at = job.created_at - timedelta(minutes=10)
        db.commit()
    assert api.detail(job_id)["upload_interrupted"] is True


def test_queue_status_reports_holds(api):
    with api.worker.held("Paused while the AI model changes"):
        queue = api.client.get(BASE).json()["queue"]
        assert queue["system_paused"] is True
        assert queue["reason"] == "Paused while the AI model changes"
    assert api.client.get(BASE).json()["queue"]["system_paused"] is False


def test_probe_endpoint_clears_a_system_pause(api):
    api.worker._set_system_reason("Not enough free disk space on the image library drive")
    r = api.client.post(f"{BASE}/queue/probe")
    assert r.status_code == 200 and r.json()["system_paused"] is False


def test_purge_refused_while_import_has_open_work(api):
    job_id = api.create()
    api.manifest(job_id, [{"relative_path": "A/G/a.png"}])
    r = api.client.delete("/api/v1/system/library")
    assert r.status_code == 409


def test_row_deleted_mid_request_is_404_not_500():
    import asyncio

    from sqlalchemy.exc import NoResultFound
    from starlette.requests import Request

    from backend.app.main import not_found_handler

    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
    response = asyncio.run(not_found_handler(request, NoResultFound()))
    assert response.status_code == 404
