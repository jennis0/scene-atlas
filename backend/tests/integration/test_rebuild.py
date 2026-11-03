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


def test_a_crash_during_the_swap_is_finished_by_the_next_start(api, backup, monkeypatch):
    with api.SessionLocal() as db:
        lr.check(db)
        lr.build(db)
    lr.request_swap()
    real = lr._move
    moves = []

    def crash_on_the_third(src, dest):
        moves.append(src)
        if len(moves) == 3:
            raise OSError("power cut")
        real(src, dest)

    monkeypatch.setattr(lr, "_move", crash_on_the_third)
    api.vectors.close()
    with pytest.raises(OSError):
        lr.swap_if_pending()
    monkeypatch.setattr(lr, "_move", real)
    _restart(api, monkeypatch)
    assert _snapshot(api) == backup


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
            assert api.client.post(f"{self.URL}/check").status_code == 409  # nothing yet
            response = api.client.put(f"{self.URL}/upload", content=export.read_bytes())
            assert response.status_code == 200 and response.json()["staged"] is True

            job = self._wait(api, api.client.post(f"{self.URL}/check").json()["job_id"])
            assert job["status"] == "completed", job.get("error")
            assert job["result"]["lost"]["images"] == 0
            assert api.client.get(self.URL).json()["check"]["images"] == 3

            job = self._wait(api, api.client.post(f"{self.URL}/build").json()["job_id"])
            assert job["status"] == "completed", job.get("error")
            assert api.client.get(self.URL).json()["built"] is True

            monkeypatch.setattr(settings, "app_mode", "app")
            assert api.client.post(f"{self.URL}/apply").json() == {"restart": "app"}
            assert (lr.rebuild_dir() / "pending.json").is_file()
        finally:
            shutil.rmtree(lr.rebuild_dir(), ignore_errors=True)

    def test_a_bad_file_fails_its_check(self, api):
        try:
            api.client.put(f"{self.URL}/upload", content=b"not json\n")
            job = self._wait(api, api.client.post(f"{self.URL}/check").json()["job_id"])
            assert job["status"] == "failed" and "can't be read" in job["error"]
            assert api.client.post(f"{self.URL}/build").status_code == 409  # not checked
        finally:
            shutil.rmtree(lr.rebuild_dir(), ignore_errors=True)

    def test_cancel_forgets_it(self, api):
        api.client.put(f"{self.URL}/upload", content=b"x\n")
        assert api.client.delete(self.URL).status_code == 200
        assert api.client.get(self.URL).json()["staged"] is False
        shutil.rmtree(lr.rebuild_dir(), ignore_errors=True)

    def test_nothing_to_apply(self, api):
        assert api.client.post(f"{self.URL}/apply").status_code == 409
