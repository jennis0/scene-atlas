"""Rebuild from a metadata export (design/export-backup-move.md §8): check what would change,
build alongside, swap at a (simulated) restart, set aside what the backup doesn't have."""

import shutil

import pytest

from backend.app.config import settings
from backend.app.models import Image, ImageGroup
from backend.app.services import get_image_store
from backend.app.services import lancedb_service as lancedb_module
from backend.pipeline import library_format as lf
from backend.pipeline import library_rebuild as lr
from backend.pipeline import metadata_export as me

from . import test_import_metadata as round_trip
from .test_imports_api import BASE, image_bytes, import_files

library = round_trip.library  # the fixture: an edited library of three images
_snapshot = round_trip._snapshot


@pytest.fixture
def backup(api, library, tmp_path, monkeypatch):
    """A metadata export of the library, staged; then the library changes: an edit the
    rebuild undoes, and a new image the backup doesn't have."""
    monkeypatch.setattr(settings, "vector_db_path", api.vectors._path)
    before = _snapshot(api)
    export = tmp_path / "backup.jsonl.gz"
    me.export_metadata(export)
    images, _forest = library
    patch = {"name": "Renamed since"}
    assert (
        api.client.patch(f"/api/v1/images/{images['Harbour.png']}", json=patch).status_code == 200
    )
    import_files(api, {"Tom/Lighthouse.png": image_bytes(7)})
    api.worker.drain()
    lr.staged_path().parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(export, lr.staged_path())
    yield before
    shutil.rmtree(lr.rebuild_dir(), ignore_errors=True)


def _restart(api, monkeypatch):
    """What the next start does: swap, then open the moved vector table."""
    api.vectors.close()
    lr.swap_if_pending()
    svc = lancedb_module.LanceDBService(
        path=settings.vector_db_path, collection_name=api.vectors.collection_name, vector_size=8
    )
    monkeypatch.setattr(lancedb_module, "_lancedb_service", svc)
    return svc


def test_check_says_what_is_missing_and_what_will_be_lost(api, backup):
    with api.SessionLocal() as db:
        result = lr.check(db)
    assert result.images == 3 and result.groups == 2
    assert result.missing["images"] == 0
    assert result.lost["images"] == 1
    assert result.lost["groups"][0]["images"] == ["Lighthouse"]
    assert result.different_library is False and result.reembed is False
    assert lr.saved_check() == result


def test_a_missing_original_is_counted_and_left_out(api, backup, library):
    images, _forest = library
    with api.SessionLocal() as db:
        key = db.get_one(Image, images["Harbour.png"]).storage_key
    get_image_store().get_path(key).unlink()
    with api.SessionLocal() as db:
        result = lr.check(db)
        assert result.missing["images"] == 1 and result.missing_stored == 1
        assert lr.build(db)["left_out"] == 1


def test_build_swap_and_set_aside(api, backup, monkeypatch, tmp_path):
    before = backup
    with api.SessionLocal() as db:
        lr.check(db)
        assert lr.build(db)["images"] == 3
    # Nothing changes until the restart
    assert "Lighthouse" in _snapshot(api)
    lr.request_swap()

    svc = _restart(api, monkeypatch)

    assert _snapshot(api) == before  # the edit is undone, the new image's metadata gone
    with api.SessionLocal() as db:
        ids = [i for (i,) in db.query(Image.id)]
        assert db.query(ImageGroup).count() == 2
    assert set(svc.get_vectors(ids)) == set(ids)  # the vectors came with it
    assert lr.set_aside_pending()

    summary = lr.set_aside()

    assert summary["moved"] == 1 and not lr.set_aside_pending()
    folder = settings.store_images_dir / "not-in-backup" / summary["id"]
    files = [p.name for p in folder.rglob("*") if p.is_file()]
    assert lf.FILENAME in files
    assert any(f.startswith("Tom_Lighthouse") for f in files)  # named from the old library
    assert lr.set_aside()["moved"] == 0  # a re-run has nothing to do

    # The folder imports it back
    monkeypatch.setattr(settings, "app_mode", "app")
    job_id = api.create("Back")
    api.client.post(f"{BASE}/{job_id}/local-sources", json={"paths": [str(folder)]})
    api.client.post(f"{BASE}/{job_id}/seal")
    api.worker.drain()
    assert "Lighthouse" in _snapshot(api)


def _built(api):
    with api.SessionLocal() as db:
        lr.check(db)
        lr.build(db)
    lr.request_swap()


@pytest.mark.parametrize("crash_at", range(1, 7))
def test_a_crash_at_any_step_of_the_swap_is_finished_by_the_next_start(
    api, backup, monkeypatch, crash_at
):
    """Killed after any move (and the next start recreating an empty vector folder, as
    Settings() does), the next start still ends with the rebuilt database and vectors."""
    _built(api)
    real = lr._move
    moves = []

    def crash(src, dest):
        moves.append(src)
        if len(moves) == crash_at:
            raise OSError("power cut")
        real(src, dest)

    monkeypatch.setattr(lr, "_move", crash)
    api.vectors.close()
    try:
        lr.swap_if_pending()
    except OSError:
        pass
    else:
        pytest.skip(f"the swap has fewer than {crash_at} moves")
    monkeypatch.setattr(lr, "_move", real)
    settings.vector_db_path.mkdir(parents=True, exist_ok=True)  # what the next start does
    svc = _restart(api, monkeypatch)
    assert _snapshot(api) == backup
    with api.SessionLocal() as db:
        ids = [i for (i,) in db.query(Image.id)]
    assert set(svc.get_vectors(ids)) == set(ids)


def test_a_build_killed_part_way_is_not_finished(api, backup):
    part = lr.rebuild_dir() / "new.part"
    part.mkdir(parents=True)
    (part / lr.DB_NAME).write_bytes(b"half a database")
    assert not lr.is_built()
    with pytest.raises(lr.RebuildError):
        lr.request_swap()


def test_cancel_after_apply_changes_nothing_at_the_next_start(api, backup):
    _built(api)
    old = lr.rebuild_dir() / "old-earlier"
    old.mkdir()
    lr.discard()
    assert lr.swap_if_pending() is None
    assert old.exists()  # an earlier rebuild's old library isn't touched
    assert not lr.set_aside_pending()


def test_a_cover_left_out_falls_back_to_the_groups_first_image(api, library, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "vector_db_path", api.vectors._path)
    images, forest = library
    day, night = images["Golden Forest Day.png"], images["Golden Forest Night.png"]
    with api.SessionLocal() as db:
        db.get_one(ImageGroup, forest).primary_image_id = day
        db.commit()
        key = db.get_one(Image, day).storage_key
    export = tmp_path / "backup.jsonl.gz"
    me.export_metadata(export)
    get_image_store().get_path(key).unlink()
    lr.staged_path().parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(export, lr.staged_path())
    try:
        _built(api)
        _restart(api, monkeypatch)
        with api.SessionLocal() as db:
            group = db.get_one(ImageGroup, forest)
            assert group.primary_image_id == night and group.image_count == 1
    finally:
        shutil.rmtree(lr.rebuild_dir(), ignore_errors=True)


def test_a_resumed_set_aside_still_reports_what_it_set_aside(api, backup, monkeypatch):
    _built(api)
    _restart(api, monkeypatch)
    pending = (lr.rebuild_dir() / "pending.json").read_text()
    first = lr.set_aside()
    (lr.rebuild_dir() / "pending.json").write_text(pending)  # as if killed before the end
    again = lr.set_aside()
    assert again["moved"] == first["moved"] == 1 and again["folder"] == first["folder"]


def test_a_download_is_not_a_backup(api, library, tmp_path):
    _images, forest = library
    body = round_trip._download(api, group_ids=[forest])
    import io
    import zipfile

    lr.staged_path().parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(body)) as zf:
        lr.staged_path().write_bytes(zf.read(lf.FILENAME))
    try:
        with api.SessionLocal() as db, pytest.raises(lr.RebuildError, match="Import it"):
            lr.check(db)
    finally:
        shutil.rmtree(lr.rebuild_dir(), ignore_errors=True)


def test_nothing_to_swap_without_a_build(api):
    with pytest.raises(lr.RebuildError):
        lr.request_swap()
    assert lr.swap_if_pending() is None


class TestApi:
    URL = "/api/v1/library/rebuild"

    def _wait(self, api, job_id):
        import time

        for _ in range(300):
            job = api.client.get(f"/api/v1/jobs/{job_id}").json()
            if job["status"] in ("completed", "failed"):
                return job
            time.sleep(0.05)
        raise AssertionError("job did not finish")

    def test_upload_check_build_apply(self, api, library, tmp_path, monkeypatch):
        monkeypatch.setattr(settings, "vector_db_path", api.vectors._path)
        export = tmp_path / "backup.jsonl.gz"
        me.export_metadata(export)
        try:
            assert api.client.get(self.URL).json()["staged"] is False
            assert api.client.post(f"{self.URL}/check", json={}).status_code == 409  # nothing yet
            response = api.client.put(f"{self.URL}/upload", content=export.read_bytes())
            assert response.status_code == 200 and response.json()["staged"] is True

            job = self._wait(api, api.client.post(f"{self.URL}/check", json={}).json()["job_id"])
            assert job["status"] == "completed", job.get("error")
            assert job["result"]["lost"]["images"] == 0
            assert api.client.get(self.URL).json()["check"]["images"] == 3

            job = self._wait(api, api.client.post(f"{self.URL}/build", json={}).json()["job_id"])
            assert job["status"] == "completed", job.get("error")
            assert api.client.get(self.URL).json()["built"] is True

            monkeypatch.setattr(settings, "app_mode", "app")
            assert api.client.post(f"{self.URL}/apply", json={}).json() == {"restart": "app"}
            assert (lr.rebuild_dir() / "pending.json").is_file()
        finally:
            shutil.rmtree(lr.rebuild_dir(), ignore_errors=True)

    def test_a_bad_file_fails_its_check(self, api):
        try:
            api.client.put(f"{self.URL}/upload", content=b"not json\n")
            job = self._wait(api, api.client.post(f"{self.URL}/check", json={}).json()["job_id"])
            assert job["status"] == "failed" and "can't be read" in job["error"]
            assert api.client.post(f"{self.URL}/build", json={}).status_code == 409  # not checked
        finally:
            shutil.rmtree(lr.rebuild_dir(), ignore_errors=True)

    def test_cancel_forgets_it(self, api):
        api.client.put(f"{self.URL}/upload", content=b"x\n")
        assert api.client.delete(self.URL).status_code == 200
        assert api.client.get(self.URL).json()["staged"] is False
        shutil.rmtree(lr.rebuild_dir(), ignore_errors=True)

    def test_the_posts_need_a_json_body(self, api):
        assert api.client.post(f"{self.URL}/check").status_code == 422
        assert api.client.post(f"{self.URL}/apply", content=b"{}").status_code == 422

    def test_nothing_starts_while_a_rebuild_waits_for_the_restart(self, api, backup):
        _built(api)
        response = api.client.post(f"{self.URL}/check", json={})
        assert response.status_code == 409 and "restart" in response.json()["detail"]
        assert api.client.delete("/api/v1/system/library").status_code == 409

    def test_apply_refuses_a_library_changed_since_the_check(self, api, backup, library):
        images, _forest = library
        with api.SessionLocal() as db:
            lr.check(db)
            lr.build(db)
        patch = {"name": "Changed again"}
        api.client.patch(f"/api/v1/images/{images['Harbour.png']}", json=patch)
        response = api.client.post(f"{self.URL}/apply", json={})
        assert response.status_code == 409 and "changed" in response.json()["detail"]

    def test_nothing_to_apply(self, api):
        assert api.client.post(f"{self.URL}/apply", json={}).status_code == 409


def test_lost_app_data_is_rebuilt_from_a_staged_export_at_startup(
    api, library, tmp_path, monkeypatch
):
    """§8.5: no database, an export staged: built into place, set aside, thumbnails made."""
    from backend.app.services import get_thumbnail_store
    from backend.pipeline import backfill_thumbnails as bt

    monkeypatch.setattr(settings, "vector_db_path", api.vectors._path)
    before = _snapshot(api)
    export = tmp_path / "backup.jsonl.gz"
    me.export_metadata(export)
    with api.SessionLocal() as db:
        thumbs = [k for (k,) in db.query(Image.thumbnail_key) if k]
    # The app data is lost: database and thumbnails
    lost = tmp_path / "lost.db"
    lr.live_db().rename(lost)
    for key in thumbs:
        get_thumbnail_store().get_path(key).unlink(missing_ok=True)
    lr.staged_path().parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(export, lr.staged_path())
    try:
        assert lr.build_in_place() is not None
        assert _snapshot(api) == before
        assert lr.set_aside_pending()
        summary = lr.after_rebuild()
        assert summary["moved"] == 0  # every file in the store was in the export
        assert summary["thumbnails"]["made"] == len(thumbs)
        with api.SessionLocal() as db:
            keys = [k for (k,) in db.query(Image.thumbnail_key)]
        assert all(get_thumbnail_store().get_path(k).is_file() for k in keys)
        assert bt.backfill_thumbnails()["made"] == 0  # nothing left to make
    finally:
        shutil.rmtree(lr.rebuild_dir(), ignore_errors=True)


def test_a_staged_export_is_ignored_while_there_is_a_database(api, backup):
    assert lr.build_in_place() is None  # never replaces a working library


def test_a_bad_staged_export_is_set_aside_not_tried_again(api, tmp_path):
    lost = tmp_path / "lost.db"
    lr.live_db().rename(lost)
    lr.staged_path().parent.mkdir(parents=True, exist_ok=True)
    lr.staged_path().write_text("not json\n")
    try:
        with pytest.raises(lf.FormatError):
            lr.build_in_place()
        lr.set_aside_failed_export()
        assert not lr.staged_path().exists()
        assert lr.build_in_place() is None
    finally:
        lost.rename(lr.live_db())
        shutil.rmtree(lr.rebuild_dir(), ignore_errors=True)
