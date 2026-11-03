"""Export metadata (design/export-backup-move.md §4): the job writes a complete gzipped
library file of one moment, with every vector, or no file at all; the API starts it,
reports on it and serves it back."""

import gzip
import os
import time

import numpy as np
import pytest
from sqlalchemy import update

from backend.app.config import settings
from backend.app.models import Image, ImageGroup, Tag
from backend.app.models.database import Color
from backend.app.services import clip_service, shutdown
from backend.app.services import lancedb_service as lancedb_module
from backend.app.services.job_runner import get_job_runner
from backend.app.services.shutdown import ShutdownRequested
from backend.pipeline import library_format as lf
from backend.pipeline import metadata_export as me
from backend.tests.conftest import TEST_VECTOR_SIZE


@pytest.fixture
def library(tmp_db, lancedb_service, tmp_path, monkeypatch):
    """Three groups of two and an ungrouped image, with tags and colours; every image but
    the ungrouped one has a vector."""
    engine, SessionLocal = tmp_db
    # Restored by this fixture's own teardown, not monkeypatch: monkeypatch unwinds after
    # test_client's teardown, and would leave the app on this test's database afterwards.
    previous_url = settings.database_url
    settings.database_url = str(engine.url)
    monkeypatch.setattr(settings, "metadata_exports_dir", tmp_path / "exports")
    monkeypatch.setattr(clip_service, "get_effective_model_name", lambda: "small")
    with SessionLocal() as db:
        groups = [ImageGroup(base_name=name, author="Czepeku") for name in ("A", "B", "C")]
        db.add_all(groups)
        db.flush()
        images = [
            Image(
                filename=f"{g.base_name}{n}.png", storage_key=f"{g.base_name}{n}.png", group_id=g.id
            )
            for g in groups
            for n in (1, 2)
        ]
        images.append(Image(filename="loose.png", storage_key="loose.png"))
        db.add_all(images)
        db.flush()
        db.add(Tag(image_id=images[0].id, category="season", value="winter"))
        db.add(Color(image_id=images[0].id, color_hex="#112233", percentage=50.0, color_order=1))
        db.commit()
        ids = [img.id for img in images]
        group_ids = [g.id for g in groups]
    vectors = {
        i: np.random.default_rng(i).random(TEST_VECTOR_SIZE, dtype=np.float32) for i in ids[:-1]
    }
    lancedb_service.batch_add_embeddings(
        [{"image_id": i, "embedding": v.tolist(), "metadata": {}} for i, v in vectors.items()]
    )
    yield ids, group_ids, vectors, SessionLocal
    settings.database_url = previous_url


def _read(path) -> list:
    with lf.open_file(path) as fp:
        return list(lf.read_lines(fp))


def _images(lines) -> list[lf.ImageEntry]:
    return [img for ln in lines if isinstance(ln, lf.GroupLine) for img in ln.images]


def test_export_writes_every_image_with_its_vector(library, tmp_path):
    ids, _group_ids, vectors, _ = library
    progress = []
    target = tmp_path / "out" / "lib.jsonl.gz"

    result = me.export_metadata(target, lambda done, total, _msg: progress.append((done, total)))

    assert result == {
        "path": str(target),
        "name": target.name,
        "images": 7,
        "bytes": target.stat().st_size,
    }
    lines = _read(target)
    header = lines[0]
    assert isinstance(header, lf.Header) and header.kind == "library"
    assert header.model is not None
    assert (header.model.name, header.model.dim) == ("small", TEST_VECTOR_SIZE)
    images = {img.id: img for img in _images(lines)}
    assert list(images) == ids
    for image_id, expected in vectors.items():
        vector = images[image_id].vector
        assert vector is not None
        np.testing.assert_array_equal(lf.decode_vector(vector, TEST_VECTOR_SIZE), expected)
    assert images[ids[-1]].vector is None  # no vector in LanceDB: left out, not invented
    assert images[ids[0]].tags[0].value == "winter"
    assert images[ids[0]].colors == [("#112233", 50.0)]
    assert progress[-1] == (7, 7)
    # Nothing left behind: no partial file, no scratch vectors
    assert os.listdir(target.parent) == [target.name]
    assert not any(settings.metadata_exports_dir.iterdir())


def test_the_file_is_a_snapshot_while_the_library_changes(library, tmp_path, monkeypatch):
    """Writes from another connection mid-export (a regroup, a new image) don't reach the
    file: each image is in it once, as it was when the export began."""
    ids, group_ids, _vectors, SessionLocal = library
    monkeypatch.setattr(lf, "_GROUP_BATCH", 1)  # a query per group, so writes land between them
    target = tmp_path / "lib.jsonl.gz"
    changed = []

    def meanwhile(done, _total, _msg):
        if changed:
            return
        changed.append(done)
        with SessionLocal() as other:
            # Move a not-yet-exported image of group C into group A, already written
            other.execute(update(Image).where(Image.id == ids[4]).values(group_id=group_ids[0]))
            other.add(Image(filename="new.png", storage_key="new.png", group_id=group_ids[2]))
            other.commit()

    me.export_metadata(target, meanwhile)

    lines = _read(target)
    exported = [img.id for img in _images(lines)]
    assert sorted(exported) == sorted(ids)  # each once, and not the new image
    groups = {ln.group.base_name: [i.id for i in ln.images] for ln in lines[1:] if ln.group}
    assert groups["C"] == [ids[4], ids[5]]  # where it was when the export began


def test_vectors_are_packed_however_sparse_the_ids(tmp_path):
    """The scratch file holds the vectors there are, not one slot per possible id."""

    class Table:
        vector_size = 4

        def iter_vectors(self):
            yield np.array([3, 900_000]), np.ones((2, 4), dtype=np.float32)
            yield np.array([42]), np.full((1, 4), 2.0, dtype=np.float32)

    scratch = tmp_path / "v.vectors"
    with me._vector_lookup(Table(), 1_000_000, scratch) as lookup:  # type: ignore[arg-type]
        assert scratch.stat().st_size == 3 * 4 * 4
        found = lookup([3, 42, 900_000, 7, 5_000_000])
    assert sorted(found) == [3, 42, 900_000]
    np.testing.assert_array_equal(found[42], [2.0] * 4)
    assert not scratch.exists()


def test_unreadable_vectors_fail_the_export_and_leave_no_file(
    library, tmp_path, lancedb_service, monkeypatch
):
    def broken(*_args, **_kwargs):
        raise OSError("disk read error")
        yield  # pragma: no cover

    monkeypatch.setattr(lancedb_service, "iter_vectors", broken)
    target = tmp_path / "out" / "lib.jsonl.gz"
    with pytest.raises(OSError, match="disk read error"):
        me.export_metadata(target)
    assert not any(target.parent.iterdir())
    assert not any(settings.metadata_exports_dir.iterdir())


def test_no_vectors_table_fails_the_export(library, tmp_path, monkeypatch):
    def unavailable():
        raise RuntimeError("LanceDB could not be opened")

    monkeypatch.setattr(lancedb_module, "get_lancedb_service", unavailable)
    with pytest.raises(RuntimeError, match="could not be opened"):
        me.export_metadata(tmp_path / "lib.jsonl.gz")
    assert not (tmp_path / "lib.jsonl.gz").exists()


def test_shutdown_stops_the_export_and_leaves_no_file(library, tmp_path, monkeypatch):
    target = tmp_path / "lib.jsonl.gz"
    with pytest.raises(ShutdownRequested):
        me.export_metadata(target, lambda *_: shutdown.request_shutdown())
    assert list(tmp_path.glob("lib.jsonl.gz*")) == []


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
    assert me.latest_export(folder) == fresh


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
        monkeypatch.setattr(settings, "app_mode", "server")
        return test_client

    def test_server_export_is_downloaded_and_reported(self, client):
        assert client.get("/api/v1/library/metadata-export").json() == {
            "job_id": None,
            "latest": None,
        }
        response = client.post("/api/v1/library/metadata-export", json={})
        assert response.status_code == 202
        job = _wait(response.json()["job_id"])
        assert job["status"] == "completed", job["error"]
        name = job["result"]["name"]
        assert me.is_export_name(name)
        # Settings, reopened, finds it
        assert client.get("/api/v1/library/metadata-export").json()["latest"] == name

        download = client.get(f"/api/v1/library/metadata-export/{name}")
        assert download.status_code == 200
        assert download.headers["content-type"] == "application/gzip"
        assert name in download.headers["content-disposition"]
        path = settings.metadata_exports_dir / "copy.jsonl"
        path.write_bytes(gzip.decompress(download.content))
        assert len(_images(_read(path))) == 7

    def test_a_running_export_is_reported_and_not_started_twice(self, client, monkeypatch):
        runner = get_job_runner()
        monkeypatch.setattr(runner, "get_active_job_id", lambda name: "job-9")
        monkeypatch.setattr(runner, "has_active_job", lambda name: True)
        assert client.get("/api/v1/library/metadata-export").json()["job_id"] == "job-9"
        assert client.post("/api/v1/library/metadata-export", json={}).status_code == 409

    def test_no_export_while_the_vectors_are_being_rebuilt(self, client):
        runner = get_job_runner()
        job_id = runner.submit(lambda: time.sleep(2), name="Rebuilding image embeddings")
        try:
            response = client.post("/api/v1/library/metadata-export", json={})
            assert response.status_code == 409
            assert "rebuilt" in response.json()["detail"]
        finally:
            _wait(job_id)

    def test_a_path_is_refused_in_server_mode(self, client, tmp_path):
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
        assert len(_images(_read(target))) == 7

    @pytest.mark.parametrize(
        "path",
        [
            "relative/x.jsonl.gz",
            "/no/such/folder/x.jsonl.gz",
            "{tmp}",
            "{data}/battlemap.db",
            "{data}/x.jsonl.gz",
            "{store}/x.jsonl.gz",
        ],
    )
    def test_bad_desktop_paths(self, client, tmp_path, monkeypatch, path):
        # The configured folders, not stand-ins: swapping them under the running app would
        # leave its shutdown working on the wrong library.
        monkeypatch.setattr(settings, "app_mode", "app")
        settings.images_dir.mkdir(parents=True, exist_ok=True)
        response = client.post(
            "/api/v1/library/metadata-export",
            json={
                "path": path.format(tmp=tmp_path, data=settings.data_dir, store=settings.images_dir)
            },
        )
        assert response.status_code == 422
        if path.startswith(("{data}", "{store}")):
            assert response.json()["detail"] == "Save it outside the library's own folders"

    @pytest.mark.parametrize(
        "name",
        [
            "%2e%2e%2fbattlemap.db",  # reaches the handler, unlike a literal ../
            "battlemap.db",
            "scene-atlas-metadata-x.jsonl.gz",
            "scene-atlas-metadata-20261103-120000.jsonl.gz%0a",
        ],
    )
    def test_only_exports_are_served(self, client, name):
        response = client.get(f"/api/v1/library/metadata-export/{name}")
        assert response.status_code == 404
        assert response.json()["detail"] == "Not Found"

    def test_an_expired_export_says_so(self, client):
        response = client.get("/api/v1/library/metadata-export/" + me.export_name())
        assert response.status_code == 404
        assert "expired" in response.json()["detail"]
