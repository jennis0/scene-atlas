"""Library identity through the app: the startup check in the lifespan, the library
endpoints, and purge rewriting the store marker (design/library-setup.md §3)."""

from __future__ import annotations

import json
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from backend.app import library_identity as li
from backend.app.config import settings
from backend.app.main import app
from backend.app.storage_lock import LOCK_FILENAME
from backend.tests.unit.test_library_identity import maps_folder

BASE = "/api/v1/library"


@pytest.fixture
def app_mode(monkeypatch):
    monkeypatch.setattr(settings, "app_mode", "app")


# POST /library/inspect


def test_inspect_is_not_found_in_server_mode(test_client, tmp_path):
    r = test_client.post(f"{BASE}/inspect", json={"linked": str(tmp_path)})
    assert r.status_code == 404


def test_inspect_counts_a_maps_folder(test_client, app_mode, tmp_path):
    r = test_client.post(f"{BASE}/inspect", json={"linked": str(maps_folder(tmp_path / "Maps", 3))})
    assert r.status_code == 200, r.text
    assert r.json() == {
        "outcome": "new",
        "message": None,
        "linked": {"kind": "maps", "image_count": 3, "capped": False},
        "library": None,
        "store_has_maps": False,
    }


def test_inspect_finds_the_running_library(test_client, app_mode):
    """The wizard compares the IDs to recognise the library it's running on."""
    library_id = test_client.get(f"{BASE}/status").json()["library_id"]
    r = test_client.post(f"{BASE}/inspect", json={"store": str(settings.store_images_dir)})
    body = r.json()
    assert body["library"]["library_id"] == library_id
    assert body["library"]["hints"]["store"] == str(settings.store_images_dir.resolve())


def test_inspect_needs_absolute_paths(test_client, app_mode):
    r = test_client.post(f"{BASE}/inspect", json={"linked": "relative/maps"})
    assert r.status_code == 422


# GET /library/status


def test_status_without_a_linked_folder(test_client, tmp_db):
    _, SessionLocal = tmp_db
    with SessionLocal() as db:
        library_id = li.get_library_id(db)
    assert library_id is not None
    assert test_client.get(f"{BASE}/status").json() == {"library_id": library_id, "linked": None}


@pytest.mark.parametrize(("mode", "shows_path"), [("app", True), ("server", False)])
def test_status_names_the_linked_folder(test_client, monkeypatch, tmp_path, mode, shows_path):
    linked = tmp_path / "Battle Maps"
    monkeypatch.setattr(settings, "app_mode", mode)
    monkeypatch.setattr(settings, "linked_library_dir", linked)
    status = test_client.get(f"{BASE}/status").json()["linked"]
    assert status["name"] == "Battle Maps"
    assert status["state"] == "offline"
    assert status["path"] == (str(linked) if shows_path else None)
    linked.mkdir()
    assert test_client.get(f"{BASE}/status").json()["linked"]["state"] == "online"


# Startup


@pytest.fixture
def roots(tmp_path, monkeypatch):
    """A library's database and store in tmp_path, for the lifespan to open."""
    monkeypatch.setattr(settings, "ingest_worker_enabled", False)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path / 'data' / 'test.db'}")
    monkeypatch.setattr(settings, "store_images_dir", tmp_path / "images")
    (tmp_path / "data").mkdir()
    return tmp_path


def test_startup_opens_a_new_library(roots):
    with TestClient(app):
        pass
    store_marker = li.read_marker(roots / "images")
    assert store_marker is not None
    assert li.read_marker(settings.app_data_dir).library_id == store_marker.library_id  # type: ignore[union-attr]
    # A second start opens the same library.
    with TestClient(app):
        pass
    assert li.read_marker(roots / "images") == store_marker


def test_startup_refuses_another_librarys_store(roots):
    (roots / "images").mkdir()
    li.write_marker(roots / "images", li.Marker(str(uuid.uuid4()), "store", {}))
    message = li.STARTUP_MESSAGES[li.APP_DATA_NOT_HERE]
    with pytest.raises(li.LibraryMismatchError, match=message), TestClient(app):
        pass
    # Refused before the database was made.
    assert not (roots / "data" / "test.db").exists()

    # Once the database exists with its own ID, the store still isn't its.
    (roots / "images" / li.MARKER_FILENAME).unlink()
    with TestClient(app):
        pass
    li.write_marker(roots / "images", li.Marker(str(uuid.uuid4()), "store", {}))
    message = li.STARTUP_MESSAGES[li.DIFFERENT_LIBRARY]
    with pytest.raises(li.LibraryMismatchError, match=message), TestClient(app):
        pass


def test_startup_refuses_a_store_containing_the_linked_folder(roots, monkeypatch):
    monkeypatch.setattr(settings, "linked_library_dir", roots / "images" / "Maps")
    with pytest.raises(li.LibraryMismatchError), TestClient(app):
        pass


# Purge


def test_purge_rewrites_the_store_marker(test_client, tmp_db):
    store = settings.store_images_dir
    before = json.loads((store / li.MARKER_FILENAME).read_text(encoding="utf-8"))
    (store / "ab" / "cd").mkdir(parents=True)
    (store / "ab" / "cd" / "abcd.jpg").write_bytes(b"x")
    (store / LOCK_FILENAME).write_text("")

    job_id = test_client.delete("/api/v1/system/library").json()["job_id"]
    for _ in range(50):
        status = test_client.get(f"/api/v1/jobs/{job_id}").json()["status"]
        if status in ("completed", "failed"):
            break
        time.sleep(0.1)
    assert status == "completed"

    assert sorted(p.name for p in store.iterdir()) == [LOCK_FILENAME, li.MARKER_FILENAME]
    assert json.loads((store / li.MARKER_FILENAME).read_text(encoding="utf-8")) == before
