"""The full library export (design/export-backup-move.md §7): a folder of the originals in
the readable layout with metadata that re-imports them; resumable; problems skipped and
listed, a full disk stopping it."""

import errno
import gzip
import hashlib
import io
import os
import time
import zipfile
from collections import namedtuple
from pathlib import Path

import pytest

from backend.app.config import settings
from backend.app.models import Image, ImageGroup
from backend.app.services import get_image_store
from backend.app.services.job_runner import get_job_runner
from backend.pipeline import export_library as ex
from backend.pipeline import library_format as lf

from . import test_import_metadata as round_trip
from .test_imports_api import BASE

library = round_trip.library  # the fixture: an edited library of three images
_delete_all, _snapshot = round_trip._delete_all, round_trip._snapshot


def _lines(folder) -> list:
    with lf.open_file(folder / lf.FILENAME) as fp:
        return list(lf.read_lines(fp))


def test_the_folder_holds_every_image_and_metadata_that_reimports_it(
    api, library, tmp_path, monkeypatch
):
    out = tmp_path / "Export"
    progress = []
    result = ex.export_library(out, lambda done, total, _m: progress.append((done, total)))

    assert result == {"path": str(out), "images": 3, "skipped": 0, "problems": []}
    assert progress[-1] == (3, 3)
    files = sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file())
    lines = _lines(out)
    paths = sorted(img.path for ln in lines[1:] for img in ln.images)
    assert files == sorted([*paths, lf.FILENAME])  # every file has its entry, and no more
    assert any(
        p.startswith("Czepeku_Golden Forest/Czepeku_Golden Forest_Summer_Day (edited)_HG20x15[")
        for p in paths
    )
    assert any(p.startswith("Unknown_Harbour") for p in paths)  # a group of one, at the top
    assert lines[0].kind == "groups"
    with api.SessionLocal() as db:
        night = db.query(Image).filter(Image.filename.like("%Night%")).one()
        original = get_image_store().get_path(night.storage_key).read_bytes()
    (night_path,) = [p for p in paths if "_Night" in p]
    assert (out / night_path).read_bytes() == original

    # Back in, through the desktop app's folder import: as it was
    before = _snapshot(api)
    _delete_all(api)
    monkeypatch.setattr("backend.app.config.settings.app_mode", "app")
    job_id = api.create("Back")
    assert (
        api.client.post(f"{BASE}/{job_id}/local-sources", json={"paths": [str(out)]}).status_code
        == 200
    )
    assert api.client.post(f"{BASE}/{job_id}/seal").status_code == 200
    api.worker.drain()
    assert _snapshot(api) == before


def test_a_stopped_export_carries_on_without_rewriting_what_it_wrote(
    api, library, tmp_path, monkeypatch
):
    out = tmp_path / "Export"
    real_copy = ex.copy_verified
    copies = []

    def disk_fills_on_the_third(source, target, expected):
        copies.append(target.name)
        if len(copies) == 3:
            raise OSError(errno.ENOSPC, "No space left on device")
        real_copy(source, target, expected)

    monkeypatch.setattr(ex, "copy_verified", disk_fills_on_the_third)
    with pytest.raises(ex.ExportStopped):
        ex.export_library(out)
    # The forest's two files and its line are there; the harbour isn't
    assert len(_lines(out)) == 2
    forest = out / "Czepeku_Golden Forest"
    written = {p.name: p.stat().st_mtime_ns for p in forest.iterdir()}

    monkeypatch.setattr(ex, "copy_verified", real_copy)
    result = ex.export_library(out)

    assert result["images"] == 3
    assert {p.name: p.stat().st_mtime_ns for p in forest.iterdir()} == written  # not rewritten
    assert any(out.glob("Unknown_Harbour*"))
    lines = _lines(out)
    assert sum(len(ln.images) for ln in lines[1:]) == 3
    assert [type(ln) for ln in lines].count(lf.Header) == 1  # one header


def test_an_unreadable_original_is_skipped_and_listed(api, library, tmp_path):
    images, _forest = library
    with api.SessionLocal() as db:
        harbour = db.get_one(Image, images["Harbour.png"])
        get_image_store().get_path(harbour.storage_key).unlink()

    result = ex.export_library(tmp_path / "Export")

    assert result["images"] == 2 and result["skipped"] == 1
    assert "Harbour.png" in result["problems"][0]
    assert not any((tmp_path / "Export").glob("Unknown_Harbour*"))


def test_a_file_whose_bytes_changed_is_not_exported(api, library, tmp_path):
    images, _forest = library
    with api.SessionLocal() as db:
        harbour = db.get_one(Image, images["Harbour.png"])
        get_image_store().get_path(harbour.storage_key).write_bytes(b"something else")

    result = ex.export_library(tmp_path / "Export")

    assert result["skipped"] == 1 and "don't match" in result["problems"][0]
    assert not list((tmp_path / "Export").glob("*.part"))
    entries = [img.path for ln in _lines(tmp_path / "Export")[1:] for img in ln.images]
    assert not any(e.startswith("Unknown_Harbour") for e in entries)


def test_too_little_space_stops_it_before_writing(api, library, tmp_path, monkeypatch):
    Usage = namedtuple("Usage", "total used free")
    monkeypatch.setattr(ex.shutil, "disk_usage", lambda _p: Usage(10, 9, 1))
    with pytest.raises(ex.ExportStopped, match="Not enough space"):
        ex.export_library(tmp_path / "Export")
    assert list((tmp_path / "Export").iterdir()) == []  # it didn't start


def test_copy_verified_leaves_nothing_half_written(tmp_path):
    source = tmp_path / "a.png"
    source.write_bytes(b"x" * 10)
    target = tmp_path / "out" / "a.png"
    with pytest.raises(ValueError):
        ex.copy_verified(source, target, "00" * 32)
    assert not target.exists() and not list(target.parent.iterdir())
    ex.copy_verified(source, target, None)
    assert target.read_bytes() == b"x" * 10
    # Already there with the right bytes: left alone
    os.utime(target, (1, 1))
    ex.copy_verified(source, target, hashlib.sha256(b"x" * 10).hexdigest())
    assert target.stat().st_mtime == 1


def test_a_group_stopped_part_way_is_finished_without_copying_again(
    api, library, tmp_path, monkeypatch
):
    out = tmp_path / "Export"
    real_copy = ex.copy_verified
    copies = []

    def disk_fills_on_the_second(source, target, expected):
        copies.append(target.name)
        if len(copies) == 2:  # the forest's second file
            raise OSError(errno.ENOSPC, "No space left on device")
        real_copy(source, target, expected)

    monkeypatch.setattr(ex, "copy_verified", disk_fills_on_the_second)
    with pytest.raises(ex.ExportStopped):
        ex.export_library(out)
    assert len(_lines(out)) == 1  # the header only: the forest isn't finished
    (first,) = list(out.rglob("*.png"))
    written = first.stat().st_mtime_ns

    monkeypatch.setattr(ex, "copy_verified", real_copy)
    assert ex.export_library(out)["images"] == 3
    assert first.stat().st_mtime_ns == written  # found by its hash, not copied again
    assert sum(len(ln.images) for ln in _lines(out)[1:]) == 3


@pytest.mark.parametrize("damage", ["empty", "torn last line"])
def test_a_killed_export_carries_on(api, library, tmp_path, damage):
    """The process killed mid-write: an empty file, or half a line at the end."""
    out = tmp_path / "Export"
    ex.export_library(out)
    metadata = out / lf.FILENAME
    text = metadata.read_bytes()
    if damage == "empty":
        metadata.write_bytes(b"")
    else:
        last = text.rstrip(b"\n").rsplit(b"\n", 1)[0] + b"\n"
        metadata.write_bytes(last + text[len(last) : len(last) + 40])  # 40 bytes of it

    assert ex.export_library(out)["images"] == 3
    lines = _lines(out)
    assert [type(ln) for ln in lines].count(lf.Header) == 1
    paths = [img.path for ln in lines[1:] for img in ln.images]
    assert len(paths) == len(set(paths)) == 3


def test_a_group_whose_lines_were_not_all_written_is_finished(api, library, tmp_path, monkeypatch):
    """A group of several lines, killed after its first reached the disk."""
    monkeypatch.setattr(lf, "MAX_IMAGES_PER_LINE", 1)  # the forest is two lines
    out = tmp_path / "Export"
    ex.export_library(out)
    metadata = out / lf.FILENAME
    raw = metadata.read_bytes().splitlines(keepends=True)
    forest = [i for i, line in enumerate(raw) if b"Golden Forest" in line]
    assert len(forest) == 2
    metadata.write_bytes(b"".join(raw[: forest[1]]))  # its second line never arrived
    files = {p: p.stat().st_mtime_ns for p in out.rglob("*.png")}

    ex.export_library(out)

    paths = [img.path for ln in _lines(out)[1:] for img in ln.images]
    assert len(paths) == len(set(paths)) == 3
    assert sum("Golden Forest" in p for p in paths) == 2
    assert {p: p.stat().st_mtime_ns for p in out.rglob("*.png")} == files  # none copied again


def test_a_file_of_that_name_that_isnt_ours_is_left_alone(api, library, tmp_path):
    out = tmp_path / "Mine"
    out.mkdir()
    (out / lf.FILENAME).write_bytes(gzip.compress(b"someone else's\n"))
    before = (out / lf.FILENAME).read_bytes()
    with pytest.raises(ex.ExportStopped, match="something else"):
        ex.export_library(out)
    assert (out / lf.FILENAME).read_bytes() == before


def test_another_folder_with_metadata_is_not_carried_on(api, library, tmp_path):
    _images, forest = library
    body = round_trip._download(api, group_ids=[forest])
    out = tmp_path / "Download"
    with zipfile.ZipFile(io.BytesIO(body)) as zf:
        zf.extractall(out)
    with pytest.raises(ex.ExportStopped, match="something else"):
        ex.export_library(out)


def test_the_cover_is_kept_when_another_file_fails(api, library, tmp_path, monkeypatch):
    images, forest = library
    with api.SessionLocal() as db:
        night = images["Golden Forest Night.png"]
        db.get_one(ImageGroup, forest).primary_image_id = night
        db.commit()
    real_copy = ex.copy_verified

    def day_fails(source, target, expected):
        if "Day" in target.name:
            raise OSError(errno.EACCES, "Permission denied")
        real_copy(source, target, expected)

    monkeypatch.setattr(ex, "copy_verified", day_fails)
    result = ex.export_library(tmp_path / "Export")
    assert result["skipped"] == 1
    assert (tmp_path / "Export" / ex.PROBLEMS_FILE).read_text().count("\n") == 1
    (forest_line,) = [
        ln
        for ln in _lines(tmp_path / "Export")[1:]
        if ln.group and len(ln.images) > 0 and "Forest" in ln.group.base_name
    ]
    assert forest_line.group.primary is not None
    assert "Night" in forest_line.images[forest_line.group.primary].path


def _wait(api, job_id: str) -> dict:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        job = api.client.get(f"/api/v1/jobs/{job_id}").json()
        if job["status"] in ("completed", "failed"):
            return job
        time.sleep(0.05)
    raise AssertionError("export job did not finish")


class TestApi:
    URL = "/api/v1/library/full-export"

    def test_a_server_exports_into_its_images_folder_and_resumes_the_newest(
        self, api, library, monkeypatch
    ):
        monkeypatch.setattr(settings, "app_mode", "server")
        status = api.client.get(self.URL).json()
        assert status == {
            "job_id": None,
            "folder": str(settings.store_images_dir / "exports"),
            "latest": None,
        }
        response = api.client.post(self.URL, json={})
        assert response.status_code == 202, response.text
        out = Path(response.json()["path"])
        assert out.parent == settings.store_images_dir / "exports"
        job = _wait(api, response.json()["job_id"])
        assert job["status"] == "completed", job.get("error")
        assert job["result"]["images"] == 3
        assert api.client.get(self.URL).json()["latest"] == str(out)

        again = api.client.post(self.URL, json={"resume": True})
        assert again.json()["path"] == str(out)  # carried on, not a new folder
        assert _wait(api, again.json()["job_id"])["result"]["images"] == 3

    def test_a_server_keeps_one_export_at_a_time(self, api, library, monkeypatch):
        monkeypatch.setattr(settings, "app_mode", "server")
        first = api.client.post(self.URL, json={})
        _wait(api, first.json()["job_id"])
        response = api.client.post(self.URL, json={})
        assert response.status_code == 409 and "already" in response.json()["detail"]

    def test_an_export_waits_for_a_purge(self, api, monkeypatch):
        from backend.app.services.job_runner import PURGE_JOB_NAME

        monkeypatch.setattr(settings, "app_mode", "server")
        runner = get_job_runner()
        monkeypatch.setattr(runner, "has_active_job", lambda name: name == PURGE_JOB_NAME)
        assert api.client.post(self.URL, json={}).status_code == 409

    def test_the_desktop_app_refuses_another_librarys_export(
        self, api, library, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(settings, "app_mode", "app")
        _images, forest = library
        body = round_trip._download(api, group_ids=[forest])
        with zipfile.ZipFile(io.BytesIO(body)) as zf:
            zf.extractall(tmp_path / "Download")
        response = api.client.post(self.URL, json={"path": str(tmp_path / "Download")})
        assert response.status_code == 422 and "something else" in response.json()["detail"]

    def test_a_purge_waits_for_an_export(self, api, monkeypatch):
        runner = get_job_runner()
        monkeypatch.setattr(runner, "has_active_job", lambda name: name == ex.JOB_NAME)
        response = api.client.delete("/api/v1/system/library")
        assert response.status_code == 409 and "exported" in response.json()["detail"]

    def test_a_folder_a_file_manager_has_shown_is_still_empty(self, api, tmp_path, monkeypatch):
        monkeypatch.setattr(settings, "app_mode", "app")
        (tmp_path / "New").mkdir()
        (tmp_path / "New" / ".DS_Store").write_bytes(b"x")
        (tmp_path / "New" / "Thumbs.db").write_bytes(b"x")
        assert api.client.post(self.URL, json={"path": str(tmp_path / "New")}).status_code == 202

    def test_a_server_refuses_a_folder(self, api, tmp_path, monkeypatch):
        monkeypatch.setattr(settings, "app_mode", "server")
        assert api.client.post(self.URL, json={"path": str(tmp_path)}).status_code == 422

    def test_the_desktop_app_exports_into_the_folder_it_chose(
        self, api, library, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(settings, "app_mode", "app")
        out = tmp_path / "Picked"
        out.mkdir()
        response = api.client.post(self.URL, json={"path": str(out), "include_linked": False})
        assert response.status_code == 202, response.text
        assert _wait(api, response.json()["job_id"])["result"]["images"] == 3
        # Picked again: it's an export, so it carries on
        assert api.client.post(self.URL, json={"path": str(out)}).status_code == 202

    @pytest.mark.parametrize("case", ["none", "relative", "missing", "not empty", "store", "data"])
    def test_bad_desktop_folders(self, api, tmp_path, monkeypatch, case):
        monkeypatch.setattr(settings, "app_mode", "app")
        settings.images_dir.mkdir(parents=True, exist_ok=True)
        (tmp_path / "Full").mkdir()
        (tmp_path / "Full" / "notes.txt").write_text("mine")
        path = {
            "none": None,
            "relative": "Export",
            "missing": str(tmp_path / "nope"),
            "not empty": str(tmp_path / "Full"),
            "store": str(settings.images_dir),
            "data": str(settings.data_dir),
        }[case]
        assert api.client.post(self.URL, json={"path": path}).status_code == 422

    def test_one_export_at_a_time(self, api, monkeypatch):
        monkeypatch.setattr(settings, "app_mode", "server")
        runner = get_job_runner()
        monkeypatch.setattr(runner, "has_active_job", lambda name: name == ex.JOB_NAME)
        assert api.client.post(self.URL, json={}).status_code == 409
