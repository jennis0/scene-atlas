"""Export metadata (design/export-backup-move.md §4): the job writes a complete gzipped
library file, or nothing, and the API starts it and serves it back."""

import gzip
import io
import os
import time

import numpy as np
import pytest

from backend.app.config import settings
from backend.app.models import Image, ImageGroup
from backend.app.services import clip_service
from backend.app.services.job_runner import get_job_runner
from backend.pipeline import library_format as lf
from backend.pipeline import metadata_export as me
from backend.tests.conftest import TEST_VECTOR_SIZE


@pytest.fixture
def library(tmp_db, lancedb_service, tmp_path, monkeypatch):
    """Three images (one without a vector) in the test database and LanceDB."""
    engine, SessionLocal = tmp_db
    monkeypatch.setattr(settings, "database_url", str(engine.url))
    monkeypatch.setattr(settings, "metadata_exports_dir", tmp_path / "exports")
    monkeypatch.setattr(clip_service, "get_effective_model_name", lambda: "small")
    with SessionLocal() as db:
        group = ImageGroup(base_name="Forest", author="Czepeku")
        db.add(group)
        db.flush()
        images = [
            Image(filename=f"{n}.png", storage_key=f"{n * 32}.png", name=n, group_id=group.id)
            for n in ("a", "b", "c")
        ]
        db.add_all(images)
        db.commit()
        ids = [img.id for img in images]
    vectors = {
        i: np.random.default_rng(i).random(TEST_VECTOR_SIZE, dtype=np.float32) for i in ids[:2]
    }
    lancedb_service.batch_add_embeddings(
        [{"image_id": i, "embedding": v.tolist(), "metadata": {}} for i, v in vectors.items()]
    )
    return ids, vectors


def _read(path):
    with gzip.open(path, "rt", encoding="utf-8") as fp:
        return list(lf.read_lines(io.StringIO(fp.read())))


def test_export_writes_every_image_with_its_vector(library, tmp_path):
    ids, vectors = library
    progress = []
    target = tmp_path / "out" / "lib.jsonl.gz"

    result = me.export_metadata(target, lambda done, total, _msg: progress.append((done, total)))

    assert result == {
        "path": str(target),
        "name": target.name,
        "images": 3,
        "bytes": target.stat().st_size,
    }
    header, line = _read(target)
    assert isinstance(header, lf.Header) and header.kind == "library"
    assert header.model is not None and header.model.dim == TEST_VECTOR_SIZE
    assert isinstance(line, lf.GroupLine)
    assert [i.id for i in line.images] == ids
    for entry in line.images[:2]:
        assert entry.vector is not None and entry.id is not None
        np.testing.assert_array_equal(
            lf.decode_vector(entry.vector, TEST_VECTOR_SIZE), vectors[entry.id]
        )
    assert line.images[2].vector is None  # no vector in LanceDB: left out, not invented
    assert progress[-1] == (3, 3)
    # Nothing left behind: no partial file, no scratch vectors
    assert os.listdir(target.parent) == [target.name]
    assert not any(settings.metadata_exports_dir.iterdir())


def test_a_failed_export_leaves_no_file(library, tmp_path, lancedb_service, monkeypatch):
    def broken(*_args, **_kwargs):
        raise OSError("disk read error")
        yield  # pragma: no cover

    monkeypatch.setattr(lancedb_service, "iter_vectors", broken)
    target = tmp_path / "out" / "lib.jsonl.gz"
    with pytest.raises(OSError, match="disk read error"):
        me.export_metadata(target)
    assert not target.parent.exists() or not any(target.parent.iterdir())
    assert not any(settings.metadata_exports_dir.iterdir())


def test_clean_exports_removes_leftovers_and_expired_exports(tmp_path):
    folder = tmp_path / "exports"
    folder.mkdir()
    fresh = folder / me.export_name()
    old = folder / "scene-atlas-metadata-20200101-000000.jsonl.gz"
    for path in (
        fresh,
        old,
        folder / "x.jsonl.gz.part",
        folder / "abc.vectors",
        folder / "notes.txt",
    ):
        path.write_text("x")
    week_ago = time.time() - 7 * 24 * 3600
    os.utime(old, (week_ago, week_ago))

    assert me.clean_exports(folder) == 3
    assert sorted(p.name for p in folder.iterdir()) == sorted([fresh.name, "notes.txt"])


def _wait(job_id: str) -> dict:
    runner = get_job_runner()
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        record = runner.get_job(job_id)
        if record and record.status in ("completed", "failed"):
            return record.to_dict()
        time.sleep(0.05)
    raise AssertionError("export job did not finish")


class TestApi:
    @pytest.fixture
    def client(self, test_client, library, tmp_path, monkeypatch):
        monkeypatch.setattr(settings, "metadata_exports_dir", tmp_path / "exports")
        return test_client

    def test_server_export_is_downloaded(self, client):
        response = client.post("/api/v1/library/metadata-export", json={})
        assert response.status_code == 202
        job = _wait(response.json()["job_id"])
        assert job["status"] == "completed", job["error"]
        name = job["result"]["name"]
        assert me.EXPORT_NAME.match(name)

        download = client.get(f"/api/v1/library/metadata-export/{name}")
        assert download.status_code == 200
        assert download.headers["content-type"] == "application/gzip"
        assert name in download.headers["content-disposition"]
        lines = list(lf.read_lines(io.StringIO(gzip.decompress(download.content).decode())))
        assert sum(len(ln.images) for ln in lines if isinstance(ln, lf.GroupLine)) == 3

    def test_a_path_is_refused_in_server_mode(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(settings, "app_mode", "server")
        response = client.post(
            "/api/v1/library/metadata-export", json={"path": str(tmp_path / "x.jsonl.gz")}
        )
        assert response.status_code == 422

    def test_the_desktop_app_writes_where_it_was_told(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(settings, "app_mode", "app")
        target = tmp_path / "picked" / "mine.jsonl.gz"
        target.parent.mkdir()
        response = client.post("/api/v1/library/metadata-export", json={"path": str(target)})
        assert response.status_code == 202
        assert _wait(response.json()["job_id"])["status"] == "completed"
        assert target.is_file()

    @pytest.mark.parametrize("path", ["relative/x.jsonl.gz", "/no/such/folder/x.jsonl.gz", "{tmp}"])
    def test_bad_desktop_paths(self, client, tmp_path, monkeypatch, path):
        monkeypatch.setattr(settings, "app_mode", "app")
        response = client.post(
            "/api/v1/library/metadata-export", json={"path": path.format(tmp=tmp_path)}
        )
        assert response.status_code == 422

    @pytest.mark.parametrize(
        "name", ["../battlemap.db", "battlemap.db", "scene-atlas-metadata-x.jsonl.gz"]
    )
    def test_only_exports_are_served(self, client, name):
        assert client.get(f"/api/v1/library/metadata-export/{name}").status_code == 404

    def test_an_expired_export_says_so(self, client):
        response = client.get("/api/v1/library/metadata-export/" + me.export_name())
        assert response.status_code == 404
        assert "expired" in response.json()["detail"]

    def test_one_export_at_a_time(self, client, monkeypatch):
        monkeypatch.setattr(get_job_runner(), "has_active_job", lambda name: True)
        assert client.post("/api/v1/library/metadata-export", json={}).status_code == 409
