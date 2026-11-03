"""Move library (design/export-backup-move.md §10): copy while running, finish at the next
start, check, and leave the old folders retired but intact."""

import json
import shutil
import sqlite3

import pytest

from backend.app.config import settings
from backend.app.models import Image
from backend.app.services.image_store import ImageStore
from backend.pipeline import library_move as lm

from . import test_import_metadata as round_trip

library = round_trip.library


@pytest.fixture
def folders(api, library, tmp_path):
    """The store the library uses, and an app data folder of its own: its database (a copy
    of the test's), vectors and thumbnails."""
    old_data = tmp_path / "Old data"
    (old_data / "lancedb" / "t.lance").mkdir(parents=True)
    (old_data / "lancedb" / "t.lance" / "data").write_bytes(b"vectors")
    (old_data / "store" / "thumbnails" / "ab").mkdir(parents=True)
    (old_data / "store" / "thumbnails" / "ab" / "ab12_400.jpg").write_bytes(b"thumb")
    src = sqlite3.connect(api.SessionLocal.kw["bind"].url.database)
    dst = sqlite3.connect(old_data / lm.DB_NAME)
    src.backup(dst)
    src.close()
    dst.close()
    return old_data, settings.store_images_dir, tmp_path / "New data", tmp_path / "New images"


def _moves(old_data, old_store, new_data, new_store):
    return [
        lm.Move("app_data", old_data, new_data),
        lm.Move("store", old_store, new_store),
    ]


def test_copy_then_finish_moves_everything(api, folders):
    old_data, old_store, new_data, new_store = folders
    result = lm.copy_job(_moves(*folders))
    assert result == {"app_data": str(new_data), "store": str(new_store)}
    assert (new_store / lm.MOVING_FILE).is_file()
    assert not (new_data / lm.DB_NAME).exists()  # the live database waits for the finish

    # Meanwhile: an import adds a file, a thumbnail is deleted
    (old_store / "zz" / "zz").mkdir(parents=True, exist_ok=True)
    (old_store / "zz" / "zz" / "zzzz.png").write_bytes(b"new")
    (old_data / "store" / "thumbnails" / "ab" / "ab12_400.jpg").unlink()

    lm.finish_move(app_data=(old_data, new_data), store=(old_store, new_store))

    assert (new_store / "zz" / "zz" / "zzzz.png").read_bytes() == b"new"
    assert not (new_data / "store" / "thumbnails" / "ab" / "ab12_400.jpg").exists()
    assert (new_data / "lancedb" / "t.lance" / "data").read_bytes() == b"vectors"
    with api.SessionLocal() as db:
        keys = [k for (k,) in db.query(Image.storage_key)]
    assert all(ImageStore(new_store).get_path(k).is_file() for k in keys)
    assert not (new_store / lm.MOVING_FILE).exists()
    for old in (old_data, old_store):
        assert (old / lm.MOVED_NOTE).is_file()
    conn = sqlite3.connect(new_data / lm.DB_NAME)
    (value,) = conn.execute(
        "SELECT value_json FROM app_settings WHERE key = ?", (lm.MOVED_FROM_KEY,)
    ).fetchone()
    conn.close()
    assert json.loads(value) == {"app_data": str(old_data), "store": str(old_store)}
    # The old folders are untouched but for the note and the marker
    assert (old_data / lm.DB_NAME).is_file()


def test_a_file_missing_from_the_new_store_fails_the_finish(api, folders, library):
    old_data, old_store, new_data, new_store = folders
    lm.copy_job(_moves(*folders))
    images, _forest = library
    with api.SessionLocal() as db:
        key = db.get_one(Image, images["Harbour.png"]).storage_key
    ImageStore(old_store).get_path(key).unlink()  # gone from both: the database still has it
    ImageStore(new_store).get_path(key).unlink()

    with pytest.raises(lm.MoveError, match="aren't in the new folder"):
        lm.finish_move(app_data=(old_data, new_data), store=(old_store, new_store))
    assert not (old_store / lm.MOVED_NOTE).exists()  # the old folders stay the library


def test_a_failed_copy_is_carried_on(api, folders, monkeypatch):
    old_data, old_store, new_data, new_store = folders
    monkeypatch.setattr(settings, "data_dir", old_data)
    lm.copy_job(_moves(*folders)[1:])  # the store copied, not yet switched
    # Trying again into the same, now non-empty, folder is allowed: it is our copy
    assert lm.plan(None, str(new_store))[0].target == new_store


@pytest.mark.parametrize("case", ["relative", "not empty", "inside", "same"])
def test_bad_targets(api, folders, tmp_path, monkeypatch, case):
    old_data, old_store, _new_data, _new_store = folders
    monkeypatch.setattr(settings, "data_dir", old_data)
    full = tmp_path / "Full"
    full.mkdir()
    (full / "notes.txt").write_text("mine")
    target = {
        "relative": "Images",
        "not empty": str(full),
        "inside": str(old_store / "Sub"),
        "same": str(old_data),
    }[case]
    with pytest.raises(lm.MoveError):
        lm.plan(None, target)


def test_old_folders_are_deleted_only_with_the_note(api, folders, tmp_path):
    old_data, old_store, new_data, new_store = folders
    elsewhere = tmp_path / "Elsewhere"
    elsewhere.mkdir()
    with api.SessionLocal() as db:
        from backend.app.models.database import AppSetting

        db.add(
            AppSetting(
                key=lm.MOVED_FROM_KEY,
                value_json=json.dumps({"app_data": str(old_data), "store": str(elsewhere)}),
            )
        )
        db.commit()
        (old_data / lm.MOVED_NOTE).write_text("moved")
        assert lm.moved_from(db) == {"app_data": str(old_data)}  # no note: not offered
        assert lm.delete_old(db) == 1
    assert not old_data.exists() and elsewhere.exists()


def test_the_api_is_desktop_only(api, monkeypatch):
    monkeypatch.setattr(settings, "app_mode", "server")
    assert api.client.get("/api/v1/library/move").status_code == 404


def test_the_api_starts_the_copy(api, folders, monkeypatch):
    old_data, old_store, new_data, new_store = folders
    monkeypatch.setattr(settings, "app_mode", "app")
    response = api.client.post("/api/v1/library/move", json={"store": str(new_store)})
    assert response.status_code == 202, response.text
    job = _wait(api, response.json()["job_id"])
    assert job["status"] == "completed", job.get("error")
    assert job["result"] == {"store": str(new_store)}
    bad = api.client.post("/api/v1/library/move", json={"store": "relative"})
    assert bad.status_code in (409, 422)
    shutil.rmtree(new_store, ignore_errors=True)


def _wait(api, job_id):
    import time

    for _ in range(300):
        job = api.client.get(f"/api/v1/jobs/{job_id}").json()
        if job["status"] in ("completed", "failed"):
            return job
        time.sleep(0.05)
    raise AssertionError("job did not finish")
