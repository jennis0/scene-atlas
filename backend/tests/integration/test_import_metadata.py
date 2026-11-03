"""Import recognition (design/export-backup-move.md §6): a download re-imports with its
metadata. Round trips through the real endpoints: import, edit, download, delete, import
the zip again, and compare."""

import io
import zipfile

import pytest

from backend.app.models import Image, ImageGroup, ImportJob, Tag
from backend.pipeline import import_metadata
from backend.pipeline import metadata_export as me
from backend.pipeline.library_format import FILENAME

from .test_imports_api import BASE, image_bytes, import_files

H = "ab" * 32  # the "installed" encoder, for vectors that fit
SAME_SITE = {"Sec-Fetch-Site": "same-origin"}


@pytest.fixture
def library(api, monkeypatch):
    """A group of two maps (one gridded, tagged, in a subgroup) and a lone scene, imported
    and edited through the API."""
    monkeypatch.setattr(
        me, "model_info", lambda svc: {"name": "small", "encoder_sha256": H, "dim": 8}
    )
    monkeypatch.setattr(import_metadata, "_installed_model", lambda: (H, 8))
    files = {
        "Czepeku/Golden Forest/Golden Forest Day.png": image_bytes(1),
        "Czepeku/Golden Forest/Golden Forest Night.png": image_bytes(2),
        "Tom/Harbour.png": image_bytes(3),
    }
    import_files(api, files)
    api.worker.drain()
    with api.SessionLocal() as db:
        images = {img.filename: img.id for img in db.query(Image)}
        day = images["Golden Forest Day.png"]
        forest = db.get_one(Image, day).group_id
    patch = {"gridded": True, "grid_type": "hex", "grid_width": 20, "grid_height": 15,
             "subgroup": "Summer", "name": "Day (edited)"}  # fmt: skip
    assert api.client.patch(f"/api/v1/images/{day}", json=patch).status_code == 200
    harbour = images["Harbour.png"]
    assert (
        api.client.patch(f"/api/v1/images/{harbour}", json={"image_type": "scene"}).status_code
        == 200
    )
    tag = {"category": "season", "value": "summer", "source": "manual"}
    assert api.client.post(f"/api/v1/tags/image/{day}", json=tag).status_code == 200
    return images, forest


def _snapshot(api) -> dict:
    """What a round trip must keep, by image name."""
    with api.SessionLocal() as db:
        out = {}
        for img in db.query(Image).filter(Image.awaiting_grouping.is_(False)):
            group = db.get(ImageGroup, img.group_id) if img.group_id else None
            out[img.name] = {
                "type": img.image_type,
                "grid": (img.gridded, img.grid_type, img.grid_width, img.grid_height),
                "subgroup": img.subgroup,
                "tags": sorted(
                    (t.category, t.value, t.source)
                    for t in db.query(Tag).filter_by(image_id=img.id)
                ),
                "group": (group.uid, group.base_name, group.author) if group else None,
            }
        return out


def _download(api, group_ids=(), image_ids=()) -> bytes:
    response = api.client.post(
        "/api/v1/downloads",
        data={
            "group_ids": ",".join(map(str, group_ids)),
            "image_ids": ",".join(map(str, image_ids)),
        },
        headers=SAME_SITE,
    )
    assert response.status_code == 200, response.text
    return response.content


def _delete_all(api) -> None:
    with api.SessionLocal() as db:
        ids = [i for (i,) in db.query(Image.id)]
    for image_id in ids:
        assert api.client.delete(f"/api/v1/images/{image_id}").status_code == 200


def _import_zip(api, body: bytes, name: str) -> str:
    job_id = api.create("Again")
    response = api.client.put(f"{BASE}/{job_id}/archives", params={"name": name}, content=body)
    assert response.status_code == 200, response.text
    assert api.client.post(f"{BASE}/{job_id}/seal").status_code == 200
    api.worker.drain()
    return job_id


def test_a_download_reimports_as_it_was(api, library, monkeypatch):
    images, forest = library
    before = _snapshot(api)
    body = _download(api, group_ids=[forest], image_ids=[images["Harbour.png"]])
    _delete_all(api)
    embedded = []
    monkeypatch.setattr(
        "backend.pipeline.tasks.embedding_generation.batch_generate_clip_embeddings",
        lambda paths, **kw: embedded.extend(paths) or [[0.1] * 8 for _ in paths],
    )

    job_id = _import_zip(api, body, "Czepeku_Golden Forest.zip")

    assert _snapshot(api) == before  # names, types, grids, subgroups, tags and group uids
    assert embedded == []  # every vector came with the metadata
    detail = api.detail(job_id)
    assert detail["with_metadata"] is True and detail["metadata_note"] is None
    assert detail["counts"]["done"] == 3
    # The report's groups and Undo work as for any import
    assert detail["group_count"] >= 1
    assert api.client.delete(f"{BASE}/{job_id}").status_code == 200
    with api.SessionLocal() as db:
        assert db.query(Image).count() == 0


def test_a_file_of_a_group_still_in_the_library_joins_it(api, library):
    images, forest = library
    body = _download(api, group_ids=[forest])
    night = images["Golden Forest Night.png"]
    assert api.client.delete(f"/api/v1/images/{night}").status_code == 200

    job_id = _import_zip(api, body, "Forest.zip")

    detail = api.detail(job_id)
    assert detail["counts"]["done"] == 1 and detail["counts"]["duplicate"] == 1
    with api.SessionLocal() as db:
        back = db.query(Image).filter(Image.filename.like("%Night%")).one()
        assert back.group_id == forest  # the same group, found by its uid
        assert db.query(ImageGroup).count() == 2  # nothing new minted


def test_files_without_an_entry_import_as_usual(api, library):
    images, forest = library
    body = _download(api, group_ids=[forest])
    _delete_all(api)
    buf = io.BytesIO(body)
    with zipfile.ZipFile(buf, "a") as zf:
        zf.writestr("Extra/Lone Map.png", image_bytes(9))

    _import_zip(api, buf.getvalue(), "Forest.zip")

    with api.SessionLocal() as db:
        extra = db.query(Image).filter_by(filename="Lone Map.png").one()
        assert extra.group_id is not None and extra.awaiting_grouping is False
        assert db.query(Image).count() == 3


def test_metadata_that_cant_be_read_leaves_a_note_and_the_files_import(api, library):
    images, forest = library
    body = _download(api, group_ids=[forest])
    _delete_all(api)
    buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(body)) as src, zipfile.ZipFile(buf, "w") as dst:
        for name in src.namelist():
            dst.writestr(name, b"not json\n" if name == FILENAME else src.read(name))

    job_id = _import_zip(api, buf.getvalue(), "Forest.zip")

    detail = api.detail(job_id)
    assert detail["with_metadata"] is False
    assert "couldn't be read" in detail["metadata_note"]
    assert detail["counts"]["done"] == 2
    with api.SessionLocal() as db:
        assert db.query(ImportJob).filter_by(id=job_id).one().export_model is None


def test_the_browser_sends_a_folders_metadata_before_its_files(api, library):
    images, forest = library
    body = _download(api, group_ids=[forest])
    before = {k: v for k, v in _snapshot(api).items() if k != "Harbour"}  # not downloaded
    _delete_all(api)
    with zipfile.ZipFile(io.BytesIO(body)) as zf:
        metadata = zf.read(FILENAME)
        files = {n: zf.read(n) for n in zf.namelist() if n != FILENAME}

    job_id = api.create("Folder")
    response = api.client.put(f"{BASE}/{job_id}/export-metadata", content=metadata)
    assert response.status_code == 200 and response.json() == {"loading": True}
    result = api.manifest(
        job_id, [{"relative_path": p, "size": len(d), "client_ref": p} for p, d in files.items()]
    )
    assert api.client.post(f"{BASE}/{job_id}/seal").status_code == 200
    for item in result["items"]:
        assert api.put(job_id, item["item_id"], files[item["relative_path"]]).status_code == 200
    api.worker.drain()

    assert _snapshot(api) == before


def test_a_folder_on_this_computer_imports_with_its_metadata(api, library, tmp_path, monkeypatch):
    """The desktop app imports an extracted download (a folder) in place."""
    images, forest = library
    body = _download(api, group_ids=[forest])
    before = {k: v for k, v in _snapshot(api).items() if k != "Harbour"}
    _delete_all(api)
    folder = tmp_path / "Czepeku_Golden Forest"
    with zipfile.ZipFile(io.BytesIO(body)) as zf:
        zf.extractall(folder)
    monkeypatch.setattr("backend.app.config.settings.app_mode", "app")

    job_id = api.create("Folder")
    response = api.client.post(f"{BASE}/{job_id}/local-sources", json={"paths": [str(folder)]})
    assert response.status_code == 200, response.text
    assert response.json()["skipped"] == 0  # the metadata file isn't reported as a skip
    assert api.client.post(f"{BASE}/{job_id}/seal").status_code == 200
    api.worker.drain()

    assert _snapshot(api) == before


def test_groups_are_minted_with_their_uid_and_files_keep_their_names(api, library):
    images, forest = library
    with api.SessionLocal() as db:
        uid = db.get_one(ImageGroup, forest).uid
    body = _download(api, group_ids=[forest])
    _delete_all(api)
    with api.SessionLocal() as db:
        db.query(ImageGroup).delete()  # nothing for the uid to join: it must be minted
        db.commit()

    _import_zip(api, body, "Forest.zip")

    with api.SessionLocal() as db:
        (group,) = db.query(ImageGroup).all()
        assert group.uid == uid and group.base_name == "Golden Forest"
        # The names they had, not the export's readable ones
        assert sorted(i.filename for i in db.query(Image)) == [
            "Golden Forest Day.png",
            "Golden Forest Night.png",
        ]


def test_an_auto_import_takes_its_types_from_the_metadata(api, library):
    images, _forest = library
    body = _download(api, image_ids=[images["Harbour.png"]])
    _delete_all(api)
    job_id = api.create("Again", image_type="auto")
    api.client.put(f"{BASE}/{job_id}/archives", params={"name": "H.zip"}, content=body)
    api.client.post(f"{BASE}/{job_id}/seal")
    api.worker.drain()
    with api.SessionLocal() as db:
        assert db.query(Image).one().image_type == "scene"  # as recorded, not classified


def test_a_map_whose_grid_the_metadata_doesnt_know_is_detected(api, library, monkeypatch):
    from backend.pipeline.pipeline_config import PipelineConfig

    images, forest = library
    body = _download(api, group_ids=[forest])  # Day has a grid; Night's is unknown
    _delete_all(api)
    detected = []
    monkeypatch.setattr(
        "backend.pipeline.tasks.grid_detection.detect_grid_from_image",
        lambda path, width, height, **kw: detected.append(path),
    )
    api.worker._config_loader = lambda: PipelineConfig(
        enable_image_grid_detection=True, ingestion_batch_size=8
    )
    _import_zip(api, body, "Forest.zip")
    assert len(detected) == 1
    with api.SessionLocal() as db:
        day = db.query(Image).filter(Image.filename == "Golden Forest Day.png").one()
        assert (day.grid_type, day.grid_width, day.grid_source) == ("hex", 20, "user")


def test_entries_are_deleted_once_the_import_is_grouped(api, library):
    from backend.app.models import ImportExportEntry

    _images, forest = library
    body = _download(api, group_ids=[forest])
    _delete_all(api)
    _import_zip(api, body, "Forest.zip")
    with api.SessionLocal() as db:
        assert db.query(ImportExportEntry).count() == 0


def test_a_seal_while_the_metadata_loads_waits_for_it(api, library, monkeypatch):
    """The browser's metadata loads in the background; a seal can arrive first, and the
    job's files must not import before it's done."""
    import threading

    images, forest = library
    body = _download(api, group_ids=[forest])
    before = {k: v for k, v in _snapshot(api).items() if k != "Harbour"}
    _delete_all(api)
    with zipfile.ZipFile(io.BytesIO(body)) as zf:
        metadata = zf.read(FILENAME)
        files = {n: zf.read(n) for n in zf.namelist() if n != FILENAME}
    release = threading.Event()
    real = import_metadata.load_exports
    monkeypatch.setattr(
        import_metadata, "load_exports", lambda j, o: release.wait(10) and real(j, o)
    )

    job_id = api.create("Folder")
    api.client.put(f"{BASE}/{job_id}/export-metadata", content=metadata)
    result = api.manifest(
        job_id, [{"relative_path": p, "size": len(d), "client_ref": p} for p, d in files.items()]
    )
    assert api.client.post(f"{BASE}/{job_id}/seal").status_code == 200
    for item in result["items"]:
        assert api.put(job_id, item["item_id"], files[item["relative_path"]]).status_code == 200
    assert api.worker.run_once() is False  # nothing claimed while it loads
    release.set()
    api.worker.drain()

    assert _snapshot(api) == before


def test_metadata_deep_in_a_zip_is_found(api, library):
    _images, forest = library
    before = {k: v for k, v in _snapshot(api).items() if k != "Harbour"}
    body = _download(api, group_ids=[forest])
    _delete_all(api)
    buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(body)) as src, zipfile.ZipFile(buf, "w") as dst:
        for name in src.namelist():
            dst.writestr(f"Backups/2026/{name}", src.read(name))

    _import_zip(api, buf.getvalue(), "Backups.zip")

    assert _snapshot(api) == before
