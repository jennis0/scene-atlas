"""Move library (design/export-backup-move.md §10): copy while running, finish at the next
start, retire the old folders once the new ones open."""

import json
import os
import shutil
import sqlite3
import time

import pytest

from backend.app.config import settings
from backend.app.models import Image
from backend.app.models.database import AppSetting
from backend.app.services.image_store import ImageStore
from backend.pipeline import library_move as lm

from . import test_import_metadata as round_trip

library = round_trip.library


@pytest.fixture
def folders(api, library, tmp_path, monkeypatch):
    """The store the library uses, and an app data folder of its own (the running
    library's, as far as the move can tell): its database (a copy of the test's),
    vectors, thumbnails and a library marker."""
    old_data = tmp_path / "Old data"
    (old_data / "lancedb" / "t.lance").mkdir(parents=True)
    (old_data / "lancedb" / "t.lance" / "data").write_bytes(b"vectors")
    (old_data / "store" / "thumbnails" / "ab").mkdir(parents=True)
    (old_data / "store" / "thumbnails" / "ab" / "ab12_400.jpg").write_bytes(b"thumb")
    (old_data / "scene-atlas-library.json").write_text("{}")
    src = sqlite3.connect(api.SessionLocal.kw["bind"].url.database)
    dst = sqlite3.connect(old_data / lm.DB_NAME)
    src.backup(dst)
    src.close()
    dst.close()
    monkeypatch.setattr(settings, "data_dir", old_data)
    return old_data, settings.store_images_dir, tmp_path / "New data", tmp_path / "New images"


def _moves(old_data, old_store, new_data, new_store):
    return [
        lm.Move("app_data", old_data, new_data),
        lm.Move("store", old_store, new_store),
    ]


def _tree(root):
    return {
        str(p.relative_to(root)): (p.stat().st_size, p.read_bytes())
        for p in sorted(root.rglob("*"))
        if p.is_file() and p.name != ".backend.lock"  # the finish's lock, as any backend's
    }


def test_copy_finish_and_retire(api, folders, monkeypatch):
    old_data, old_store, new_data, new_store = folders
    result = lm.copy_job(_moves(*folders))
    assert result == {"app_data": str(new_data), "store": str(new_store)}
    assert lm.copy_status() == result  # Settings offers the restart, even reopened
    assert not (new_data / lm.DB_NAME).exists()  # the live database waits for the finish

    # Meanwhile: an import adds a file, a thumbnail is deleted
    (old_store / "zz" / "zz").mkdir(parents=True, exist_ok=True)
    (old_store / "zz" / "zz" / "zzzz.png").write_bytes(b"new")
    (old_data / "store" / "thumbnails" / "ab" / "ab12_400.jpg").unlink()
    before = {"data": _tree(old_data), "store": _tree(old_store)}

    lm.finish_move(app_data=(old_data, new_data), store=(old_store, new_store))

    assert (new_store / "zz" / "zz" / "zzzz.png").read_bytes() == b"new"
    assert not (new_data / "store" / "thumbnails" / "ab" / "ab12_400.jpg").exists()
    assert (new_data / "lancedb" / "t.lance" / "data").read_bytes() == b"vectors"
    assert (new_data / "scene-atlas-library.json").is_file()  # the new folders open
    with api.SessionLocal() as db:
        keys = [k for (k,) in db.query(Image.storage_key)]
    assert all(ImageStore(new_store).get_path(k).is_file() for k in keys)
    # The old folders are untouched until the new ones have opened
    assert {"data": _tree(old_data), "store": _tree(old_store)} == before

    monkeypatch.setattr(settings, "data_dir", new_data)
    with api.SessionLocal() as db:
        lm.retire_finished(db)
        row = db.get(AppSetting, lm.MOVED_FROM_KEY)
        assert json.loads(row.value_json) == {"app_data": str(old_data), "store": str(old_store)}
        assert lm.moved_from(db) == {"app_data": str(old_data), "store": str(old_store)}
    for old in (old_data, old_store):
        assert (old / lm.MOVED_NOTE).is_file()
    assert not (old_data / "scene-atlas-library.json").exists()  # no longer opens
    assert not (new_store / lm.MOVING_FILE).exists()

    # A start after that, still with the move's arguments, does nothing
    lm.finish_move(app_data=(old_data, new_data), store=(old_store, new_store))


def test_a_second_finish_before_the_retire_does_nothing(api, folders):
    old_data, old_store, new_data, new_store = folders
    lm.copy_job(_moves(*folders))
    lm.finish_move(app_data=(old_data, new_data), store=(old_store, new_store))
    (new_store / "imported-since.png").write_bytes(b"mine")
    lm.finish_move(app_data=(old_data, new_data), store=(old_store, new_store))
    assert (new_store / "imported-since.png").exists()  # not synced away


@pytest.mark.parametrize("case", ["not a copy", "same folder", "unfinished"])
def test_the_finish_refuses_a_folder_that_isnt_this_moves_copy(api, folders, tmp_path, case):
    old_data, old_store, _new_data, new_store = folders
    other = tmp_path / "Someone else's"
    other.mkdir()
    (other / "precious.txt").write_text("keep me")
    if case == "same folder":
        target = old_store
    elif case == "unfinished":
        target = new_store
        target.mkdir()
        (target / lm.MOVING_FILE).write_text(
            json.dumps({"from": str(old_store), "kind": "store", "state": None})
        )
    else:
        target = other
    with pytest.raises(lm.MoveError):
        lm.finish_move(store=(old_store, target))
    assert (other / "precious.txt").exists()


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


def test_times_rounded_by_the_target_still_match(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.write_bytes(b"x")
    b.write_bytes(b"x")
    now = time.time_ns()
    os.utime(a, ns=(now, now))
    os.utime(b, ns=(now, now - (now % 2_000_000_000)))  # FAT32's 2 s
    assert lm._same(a, b)
    b.write_bytes(b"xy")
    assert not lm._same(a, b)


def test_a_failed_copy_is_carried_on_and_can_be_cancelled(api, folders):
    old_data, old_store, new_data, new_store = folders
    lm.copy_job(_moves(*folders)[1:])
    # Trying again into the same, now non-empty, folder is allowed: it is our copy
    assert lm.plan(None, str(new_store))[0].target == new_store
    lm.cancel()
    assert not new_store.exists() and lm.copy_status() is None


@pytest.mark.parametrize("case", ["relative", "not empty", "inside", "same"])
def test_bad_targets(api, folders, tmp_path, case):
    old_data, old_store, _new_data, _new_store = folders
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
    gone, elsewhere = tmp_path / "Gone", tmp_path / "Elsewhere"
    gone.mkdir()
    elsewhere.mkdir()
    with api.SessionLocal() as db:
        db.add(
            AppSetting(
                key=lm.MOVED_FROM_KEY,
                value_json=json.dumps({"app_data": str(gone), "store": str(elsewhere)}),
            )
        )
        db.commit()
        (gone / lm.MOVED_NOTE).write_text("moved")
        (gone / "read-only.txt").write_text("x")
        os.chmod(gone / "read-only.txt", 0o444)
        assert lm.moved_from(db) == {"app_data": str(gone)}  # no note: not offered
        assert lm.delete_old(db) == {"deleted": 1, "kept": []}
    assert not gone.exists() and elsewhere.exists()


def test_an_old_folder_inside_a_live_one_is_kept_and_said(api, folders):
    old_data, old_store, _new_data, _new_store = folders
    inner = old_store / "old store"
    inner.mkdir()
    (inner / lm.MOVED_NOTE).write_text("moved")
    with api.SessionLocal() as db:
        db.add(AppSetting(key=lm.MOVED_FROM_KEY, value_json=json.dumps({"store": str(inner)})))
        db.commit()
        result = lm.delete_old(db)
        assert result["deleted"] == 0 and "by hand" in result["kept"][0]
        assert lm.moved_from(db) is not None  # still offered: nothing was deleted
    shutil.rmtree(inner)


def test_the_api_is_desktop_only(api, monkeypatch):
    monkeypatch.setattr(settings, "app_mode", "server")
    assert api.client.get("/api/v1/library/move").status_code == 404


def test_the_api_copies_then_reports_it_copied(api, folders, monkeypatch):
    old_data, old_store, new_data, new_store = folders
    monkeypatch.setattr(settings, "app_mode", "app")
    response = api.client.post("/api/v1/library/move", json={"store": str(new_store)})
    assert response.status_code == 202, response.text
    job = _wait(api, response.json()["job_id"])
    assert job["status"] == "completed", job.get("error")
    status = api.client.get("/api/v1/library/move").json()
    assert status["copied"] == {"store": str(new_store)}
    assert status["movable"] == {"app_data": True, "store": True}
    bad = api.client.post("/api/v1/library/move", json={"store": "relative"})
    assert bad.status_code == 422
    assert api.client.delete("/api/v1/library/move").status_code == 200
    assert not new_store.exists()


def _wait(api, job_id):
    for _ in range(300):
        job = api.client.get(f"/api/v1/jobs/{job_id}").json()
        if job["status"] in ("completed", "failed"):
            return job
        time.sleep(0.05)
    raise AssertionError("job did not finish")
