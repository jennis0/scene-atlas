"""Integration tests for local imports (design/local-ingest.md).

The desktop app names files and folders by path; the server lists them and the worker
reads each in place and copies it into the library. Real HTTP API, SQLite, LanceDB and
filesystem; embeddings are faked and the worker is driven with ``drain()``.
"""

from __future__ import annotations

import hashlib
import os
import sys
import zipfile
from pathlib import Path

import pytest

from backend.app.library_identity import MARKER_FILENAME
from backend.app.models import Image, ImportItem
from backend.app.services import get_image_store
from backend.app.services import ingest_state as st
from backend.pipeline.pipeline_config import PipelineConfig
from backend.pipeline.stored_format import StoredFormat

from .test_imports_api import BASE, image_bytes, import_files


@pytest.fixture
def local(api, monkeypatch):
    """The imports API as the desktop app sees it (the test client uses a loopback host)."""
    monkeypatch.setattr("backend.app.config.settings.app_mode", "app")
    return api


def write_tree(root: Path, files: dict[str, bytes]) -> None:
    for relative, data in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def tree_digest(root: Path) -> dict[str, str]:
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def add_sources(api, job_id: str, paths: list[Path | str], status: int = 200) -> dict:
    r = api.client.post(f"{BASE}/{job_id}/local-sources", json={"paths": [str(p) for p in paths]})
    assert r.status_code == status, r.text
    return r.json()


def import_local(api, paths: list[Path], label="Local") -> str:
    job_id = api.create(label)
    add_sources(api, job_id, paths)
    assert api.client.post(f"{BASE}/{job_id}/seal").status_code == 200
    return job_id


def items(api, job_id: str) -> dict[str, ImportItem]:
    with api.SessionLocal() as db:
        rows = db.query(ImportItem).filter_by(job_id=job_id).all()
        for row in rows:
            db.expunge(row)
        return {row.relative_path: row for row in rows}


def library_files() -> list[Path]:
    base = get_image_store().base_dir
    return [
        p
        for p in base.rglob("*")
        if p.is_file() and ".incoming" not in p.parts and p.name != MARKER_FILENAME
    ]


def summary(api, job_id: str) -> dict:
    return next(j for j in api.client.get(BASE).json()["jobs"] if j["id"] == job_id)


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------


def test_folder_is_listed_grouped_and_imported(local, tmp_path):
    src = tmp_path / "src"
    write_tree(
        src,
        {
            "Czepeku/Forest/Forest_Day.png": image_bytes(1),
            "Czepeku/Forest/Forest_Night.png": image_bytes(2),
            "Czepeku/Forest/._Forest_Day.png": b"junk",
            "Czepeku/Forest/readme.txt": b"hello",
        },
    )
    before = tree_digest(src)

    job_id = local.create("Czepeku")
    counts = add_sources(local, job_id, [src / "Czepeku"])
    assert counts == {"created": 2, "skipped": 1, "failed": 0, "ignored": 0}
    found = items(local, job_id)
    assert set(found) == {
        "Czepeku/Forest/Forest_Day.png",
        "Czepeku/Forest/Forest_Night.png",
        "Czepeku/Forest/readme.txt",
    }
    day = found["Czepeku/Forest/Forest_Day.png"]
    assert day.state == st.READY and day.source_path == str(src / "Czepeku/Forest/Forest_Day.png")

    detail = local.client.post(f"{BASE}/{job_id}/seal").json()
    assert detail["groups"] == []  # identified once the import has finished
    assert detail["local"] is True and detail["upload_interrupted"] is False

    local.worker.drain()
    detail = local.detail(job_id)
    assert detail["status"] == "completed"
    assert [g["group_name"] for g in detail["groups"]] == ["Forest"]
    with local.SessionLocal() as db:
        images = db.query(Image).all()
        assert len(images) == 2 and {i.author for i in images} == {"Czepeku"}
        for image in images:
            assert get_image_store().get_path(image.storage_key).exists()
            assert image.content_hash == image.stored_hash
    assert len(library_files()) == 2
    assert tree_digest(src) == before  # the source is never written


def test_file_roots_and_zips_are_kept(local, tmp_path):
    loose = tmp_path / "Loose_Map.png"
    loose.write_bytes(image_bytes(1))
    pack = tmp_path / "Pack.zip"
    with zipfile.ZipFile(pack, "w") as zf:
        zf.writestr("Pack/Cave/Cave_A.png", image_bytes(2))
        zf.writestr("Pack/Cave/Cave_B.png", image_bytes(3))

    job_id = local.create()
    counts = add_sources(local, job_id, [loose, pack])
    assert counts["created"] == 3
    assert pack.exists() and loose.exists()

    local.client.post(f"{BASE}/{job_id}/seal")
    local.worker.drain()
    assert local.detail(job_id)["counts"]["done"] == 3
    assert pack.exists() and loose.exists()


def test_zip_in_a_folder_is_named_by_it(local, tmp_path):
    creator = tmp_path / "Creator"
    creator.mkdir()
    with zipfile.ZipFile(creator / "Golden Forest.zip", "w") as zf:
        zf.writestr("Golden Forest/Day.png", image_bytes(4))
    job_id = local.create()
    add_sources(local, job_id, [creator])
    assert set(items(local, job_id)) == {"Creator/Golden Forest/Day.png"}


def test_colliding_folder_names_are_prefixed(local, tmp_path):
    write_tree(tmp_path / "A", {"Maps/Map.png": image_bytes(1)})
    write_tree(tmp_path / "B", {"Maps/Map.png": image_bytes(2)})
    job_id = local.create()
    add_sources(local, job_id, [tmp_path / "A/Maps", tmp_path / "B/Maps"])
    assert set(items(local, job_id)) == {"Maps/Map.png", "B/Maps/Map.png"}


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_symlinks_are_not_followed(local, tmp_path):
    write_tree(tmp_path / "outside", {"Secret.png": image_bytes(1)})
    write_tree(tmp_path / "Maps", {"Map.png": image_bytes(2)})
    os.symlink(tmp_path / "outside", tmp_path / "Maps/link")
    os.symlink(tmp_path / "outside/Secret.png", tmp_path / "Maps/Secret.png")
    job_id = local.create()
    add_sources(local, job_id, [tmp_path / "Maps"])
    assert set(items(local, job_id)) == {"Maps/Map.png"}


def test_adding_the_same_folder_twice_ignores_repeats(local, tmp_path):
    write_tree(tmp_path / "Maps", {"Map.png": image_bytes(1)})
    job_id = local.create()
    add_sources(local, job_id, [tmp_path / "Maps"])
    assert add_sources(local, job_id, [tmp_path / "Maps"])["ignored"] == 1


# ---------------------------------------------------------------------------
# Validation and limits
# ---------------------------------------------------------------------------


def test_server_mode_has_no_local_sources(api, tmp_path):
    job_id = api.create()
    add_sources(api, job_id, [tmp_path], status=404)


@pytest.mark.parametrize("path", ["relative/folder", "/no/such/folder"])
def test_bad_roots_are_rejected(local, path):
    job_id = local.create()
    assert "detail" in add_sources(local, job_id, [path], status=422)


def test_too_many_files_is_rejected(local, tmp_path, monkeypatch):
    monkeypatch.setattr("backend.app.config.settings.max_local_import_items", 2)
    write_tree(tmp_path / "Maps", {f"Map{i}.png": image_bytes(i) for i in range(3)})
    job_id = local.create()
    add_sources(local, job_id, [tmp_path / "Maps"], status=413)
    assert items(local, job_id) == {}


def test_sealed_import_takes_no_more_sources(local, tmp_path):
    write_tree(tmp_path / "Maps", {"Map.png": image_bytes(1)})
    job_id = import_local(local, [tmp_path / "Maps"])
    add_sources(local, job_id, [tmp_path / "Maps"], status=409)


def test_content_that_isnt_an_image_fails(local, tmp_path):
    write_tree(tmp_path / "Maps", {"Fake.png": b"not really a png"})
    job_id = import_local(local, [tmp_path / "Maps"])
    local.worker.drain()
    fake = items(local, job_id)["Maps/Fake.png"]
    assert fake.state == st.FAILED and fake.error_reason == "File content doesn't match its type"


# ---------------------------------------------------------------------------
# Duplicates and stored format
# ---------------------------------------------------------------------------


def test_reimporting_a_folder_skips_known_files_before_processing(local, tmp_path, monkeypatch):
    write_tree(tmp_path / "Maps", {"A/One.png": image_bytes(1), "A/Two.png": image_bytes(2)})
    local.worker.drain()
    import_local(local, [tmp_path / "Maps"])
    local.worker.drain()
    stored = library_files()

    write_tree(tmp_path / "Maps", {"A/Three.png": image_bytes(3)})
    decoded: list[str] = []
    from backend.pipeline import ingest_process

    real_plan = ingest_process.plan_decode
    monkeypatch.setattr(
        ingest_process,
        "plan_decode",
        lambda staged, item, cfg: (
            decoded.append(item.relative_path) or real_plan(staged, item, cfg)
        ),
    )
    second = import_local(local, [tmp_path / "Maps"])
    local.worker.drain()

    found = items(local, second)
    assert {p: i.state for p, i in found.items()} == {
        "Maps/A/One.png": st.DUPLICATE,
        "Maps/A/Two.png": st.DUPLICATE,
        "Maps/A/Three.png": st.DONE,
    }
    assert found["Maps/A/One.png"].duplicate_tier == "bytes"
    assert decoded == ["Maps/A/Three.png"]  # duplicates were never decoded
    assert len(library_files()) == len(stored) + 1
    assert local.detail(second)["status"] == "completed"


def test_duplicate_imported_as_copy_is_read_again(local, tmp_path):
    write_tree(tmp_path / "Maps", {"Map.png": image_bytes(1)})
    import_local(local, [tmp_path / "Maps"])
    local.worker.drain()
    second = import_local(local, [tmp_path / "Maps"])
    local.worker.drain()
    assert local.client.post(f"{BASE}/{second}/import-as-copy", json={}).status_code == 200
    assert items(local, second)["Maps/Map.png"].state == st.READY
    local.worker.drain()
    assert items(local, second)["Maps/Map.png"].state == st.DONE
    assert len(library_files()) == 2


def test_converted_local_import_leaves_no_temp_copy(local, tmp_path):
    local.worker._config_loader = lambda: PipelineConfig(
        enable_image_grid_detection=False, stored_format=StoredFormat(format="webp")
    )
    write_tree(tmp_path / "Maps", {"Map.png": image_bytes(1)})
    import_local(local, [tmp_path / "Maps"])
    local.worker.drain()
    with local.SessionLocal() as db:
        image = db.query(Image).one()
        assert image.storage_key.endswith(".webp")
    assert [p.suffix for p in library_files()] == [".webp"]
    incoming = get_image_store().base_dir / ".incoming"
    assert not any(p.is_file() for p in incoming.rglob("*"))


# ---------------------------------------------------------------------------
# Missing files and folders
# ---------------------------------------------------------------------------


def test_file_deleted_after_choosing_fails_and_can_be_retried(local, tmp_path):
    write_tree(tmp_path / "Maps", {"Map.png": image_bytes(1), "Other.png": image_bytes(2)})
    job_id = import_local(local, [tmp_path / "Maps"])
    moved = tmp_path / "Map.png.bak"
    (tmp_path / "Maps/Map.png").rename(moved)
    local.worker.drain()

    missing = items(local, job_id)["Maps/Map.png"]
    assert missing.state == st.FAILED
    assert missing.error_reason == "The file was moved or deleted after it was chosen"
    assert items(local, job_id)["Maps/Other.png"].state == st.DONE

    moved.rename(tmp_path / "Maps/Map.png")
    assert local.client.post(f"{BASE}/{job_id}/retry", json={}).status_code == 200
    assert items(local, job_id)["Maps/Map.png"].state == st.READY
    local.worker.drain()
    assert local.detail(job_id)["counts"]["done"] == 2


def test_missing_folder_makes_the_job_wait(local, tmp_path):
    write_tree(tmp_path / "Drive/Maps", {"A/One.png": image_bytes(1)})
    job_id = import_local(local, [tmp_path / "Drive/Maps"])
    upload_id, _ = import_files(local, {"B/Map/Two.png": image_bytes(2)})
    (tmp_path / "Drive").rename(tmp_path / "Unplugged")

    local.worker.drain()
    assert items(local, job_id)["Maps/A/One.png"].state == st.READY
    waiting = summary(local, job_id)
    assert waiting["status"] == "active"
    assert waiting["waiting_for"] == [str(tmp_path / "Drive/Maps")]
    assert local.detail(upload_id)["status"] == "completed"  # other imports carry on

    (tmp_path / "Unplugged").rename(tmp_path / "Drive")
    local.worker.drain()
    assert local.detail(job_id)["status"] == "completed"
    assert summary(local, job_id)["waiting_for"] == []


def test_folder_vanishing_mid_batch_refunds_the_item(local, tmp_path, monkeypatch):
    write_tree(tmp_path / "Drive/Maps", {"One.png": image_bytes(1)})
    job_id = import_local(local, [tmp_path / "Drive/Maps"])
    from backend.pipeline import ingest_process

    real_copy = ingest_process.shutil.copyfile

    def unplug_then_copy(src, dst):
        (tmp_path / "Drive").rename(tmp_path / "Unplugged")
        return real_copy(src, dst)

    monkeypatch.setattr(ingest_process.shutil, "copyfile", unplug_then_copy)
    local.worker.drain()
    monkeypatch.setattr(ingest_process.shutil, "copyfile", real_copy)

    item = items(local, job_id)["Maps/One.png"]
    assert item.state == st.READY and item.attempts == 0
    assert not any(p.is_file() for p in (get_image_store().base_dir / ".incoming").rglob("*"))

    (tmp_path / "Unplugged").rename(tmp_path / "Drive")
    local.worker.drain()
    assert local.detail(job_id)["status"] == "completed"


def test_undo_never_touches_the_source(local, tmp_path):
    write_tree(tmp_path / "Maps", {"A/One.png": image_bytes(1), "A/Two.png": image_bytes(2)})
    before = tree_digest(tmp_path / "Maps")
    job_id = import_local(local, [tmp_path / "Maps"])
    local.worker.drain()
    assert local.client.delete(f"{BASE}/{job_id}").status_code == 200
    assert library_files() == []
    assert tree_digest(tmp_path / "Maps") == before


def test_undo_of_an_import_that_added_nothing(local, tmp_path):
    """Regression: undo of a paused import with no images failed with StaleDataError."""
    write_tree(tmp_path / "Maps", {f"A/Map{i}.png": image_bytes(i) for i in range(3)})
    job_id = local.create()
    assert local.client.post(f"{BASE}/{job_id}/pause").status_code == 200
    add_sources(local, job_id, [tmp_path / "Maps"])
    assert local.client.post(f"{BASE}/{job_id}/seal").status_code == 200
    r = local.client.delete(f"{BASE}/{job_id}")
    assert r.status_code == 200, r.text
    assert r.json() == {"affected": 0, "status": "deleted"}
    assert local.client.get(f"{BASE}/{job_id}").status_code == 404
