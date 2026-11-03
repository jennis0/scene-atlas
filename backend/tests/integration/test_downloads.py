"""Downloads (design/export-backup-move.md §5): the check, the zip (metadata first, files in
the readable layout, every file matching its entry), the limits, missing originals, the
cross-site guard and single-image downloads."""

import io
import zipfile

import numpy as np
import pytest

from backend.app.api import downloads
from backend.app.models.database import Image, ImageGroup, Tag
from backend.app.services.image_store import ImageStore
from backend.pipeline import library_format as lf
from backend.tests.conftest import TEST_VECTOR_SIZE

SAME_SITE = {"Sec-Fetch-Site": "same-origin"}


@pytest.fixture
def library(test_client, tmp_db, lancedb_service, make_test_image, tmp_path, monkeypatch):
    """A group of two (one with a vector and a tag), a group of one and an ungrouped
    image, all with real files; and an image awaiting grouping."""
    _engine, SessionLocal = tmp_db
    store = ImageStore(tmp_path / "image_store")
    monkeypatch.setattr("backend.app.services.get_image_store", lambda: store)
    with SessionLocal() as db:
        forest = ImageGroup(base_name="Forest Map", author="AuthorA")
        cave = ImageGroup(base_name="Cave", author="AuthorA")
        db.add_all([forest, cave])
        db.flush()
        rows = [
            ("Night", "aa/bb/night.jpg", forest.id, True),
            ("Day", "aa/bb/day.jpg", forest.id, False),
            ("Cave", "cc/dd/cave.jpg", cave.id, None),
            ("Loose", "ee/ff/loose.jpg", None, None),
        ]
        images = []
        for name, key, group_id, gridded in rows:
            make_test_image(store.get_path(key), width=60, height=40)
            img = Image(
                name=name,
                filename=f"{name}.jpg",
                author="AuthorA",
                storage_key=key,
                group_id=group_id,
                gridded=gridded,
                grid_width=20 if gridded else None,
                grid_height=15 if gridded else None,
                file_size=store.get_path(key).stat().st_size,
            )
            db.add(img)
            images.append(img)
        waiting = Image(filename="w.jpg", storage_key="ee/ff/loose.jpg", awaiting_grouping=True)
        db.add(waiting)
        db.flush()
        db.add(Tag(image_id=images[0].id, category="season", value="winter"))
        db.commit()
        ids = {img.name: img.id for img in images} | {"waiting": waiting.id}
        group_ids = {"forest": forest.id, "cave": cave.id}
    vector = np.arange(TEST_VECTOR_SIZE, dtype=np.float32)
    lancedb_service.batch_add_embeddings(
        [{"image_id": ids["Night"], "embedding": vector.tolist(), "metadata": {}}]
    )
    return test_client, ids, group_ids, store


def _download(client, *, group_ids=(), image_ids=(), headers=SAME_SITE):
    return client.post(
        "/api/v1/downloads",
        data={
            "group_ids": ",".join(map(str, group_ids)),
            "image_ids": ",".join(map(str, image_ids)),
        },
        headers=headers,
    )


def _zip(response) -> zipfile.ZipFile:
    assert response.status_code == 200, response.text
    return zipfile.ZipFile(io.BytesIO(response.content))


def _metadata(zf: zipfile.ZipFile) -> list:
    return list(lf.read_lines(io.StringIO(zf.read(lf.FILENAME).decode("utf-8"))))


class TestCheck:
    def test_counts_listed_images_and_their_size(self, library):
        client, ids, group_ids, store = library
        body = {"group_ids": [group_ids["forest"]], "image_ids": [ids["Loose"], ids["waiting"]]}
        result = client.post("/api/v1/downloads/check", json=body).json()
        sizes = [store.get_path(k).stat().st_size for k in ("aa/bb/night.jpg", "aa/bb/day.jpg")]
        loose = store.get_path("ee/ff/loose.jpg").stat().st_size
        assert result == {
            "image_count": 3,
            "bytes": sum(sizes) + loose,
            "missing": 0,
            "ok": True,
            "reason": None,
        }

    def test_counts_files_that_cant_be_read(self, library):
        client, _ids, group_ids, store = library
        store.get_path("aa/bb/day.jpg").unlink()
        result = client.post("/api/v1/downloads/check", json={"group_ids": [group_ids["forest"]]})
        assert result.json()["image_count"] == 1 and result.json()["missing"] == 1
        assert result.json()["ok"] is True

    def test_refuses_nothing_and_too_much(self, library, monkeypatch):
        client, ids, group_ids, _ = library
        assert client.post("/api/v1/downloads/check", json={}).json()["ok"] is False
        monkeypatch.setattr(downloads, "MAX_FILES", 1)
        result = client.post("/api/v1/downloads/check", json={"group_ids": [group_ids["forest"]]})
        assert result.json()["ok"] is False and "at most 1" in result.json()["reason"]
        monkeypatch.setattr(downloads, "MAX_FILES", 999)
        monkeypatch.setattr(downloads, "MAX_BYTES", 10)
        result = client.post("/api/v1/downloads/check", json={"image_ids": [ids["Loose"]]})
        assert "Export library" in result.json()["reason"]


class TestDownload:
    def test_a_zip_of_files_in_the_readable_layout_with_metadata_first(self, library):
        client, ids, group_ids, store = library
        response = _download(client, group_ids=[group_ids["forest"]], image_ids=[ids["Loose"]])
        zf = _zip(response)
        assert zf.namelist() == [
            lf.FILENAME,
            "AuthorA_Forest Map/AuthorA_Forest Map_Night_G20x15[winter].jpg",
            "AuthorA_Forest Map/AuthorA_Forest Map_Day_GL.jpg",
            "AuthorA_Loose.jpg",
        ]
        assert response.headers["content-length"] == str(len(response.content))
        assert "scene-atlas-download-3-images.zip" in response.headers["content-disposition"]

        lines = _metadata(zf)
        assert lines[0].kind == "groups"
        entries = [img for ln in lines[1:] for img in ln.images]
        # The entries and the files are the same set, one for one
        assert [entry.path for entry in entries] == zf.namelist()[1:]
        night = entries[0]
        assert night.id is None and night.storage_key is None  # no library fields
        assert night.vector is not None
        np.testing.assert_array_equal(
            lf.decode_vector(night.vector, TEST_VECTOR_SIZE), np.arange(TEST_VECTOR_SIZE)
        )
        assert entries[1].vector is None
        assert zf.read(night.path) == store.get_path("aa/bb/night.jpg").read_bytes()

    def test_one_group_is_named_after_it(self, library):
        client, _ids, group_ids, _ = library
        response = _download(client, group_ids=[group_ids["cave"]])
        assert 'filename="AuthorA_Cave.zip"' in response.headers["content-disposition"]
        assert _zip(response).namelist() == [lf.FILENAME, "AuthorA_Cave.jpg"]

    def test_a_missing_original_is_left_out_of_files_and_metadata(self, library):
        client, ids, group_ids, store = library
        store.get_path("aa/bb/day.jpg").unlink()
        zf = _zip(_download(client, group_ids=[group_ids["forest"]]))
        assert len(zf.namelist()) == 2
        names = [img.name for ln in _metadata(zf)[1:] for img in ln.images]
        assert names == ["Night"]

    def test_images_awaiting_grouping_are_never_downloaded(self, library):
        client, ids, _group_ids, _ = library
        assert _download(client, image_ids=[ids["waiting"]]).status_code == 404

    def test_too_much_is_refused_as_text_the_apps_frame_can_show(self, library, monkeypatch):
        client, _ids, group_ids, _ = library
        monkeypatch.setattr(downloads, "MAX_FILES", 1)
        response = _download(client, group_ids=[group_ids["forest"]])
        assert response.status_code == 413
        assert response.headers["content-type"].startswith("text/plain")
        assert response.headers["x-frame-options"] == "SAMEORIGIN"
        assert "at most 1" in response.text

    def test_the_zip_itself_must_fit_the_import_limit(self, library, monkeypatch):
        client, _ids, group_ids, _ = library
        monkeypatch.setattr(downloads, "MAX_ZIP_BYTES", 100)
        assert _download(client, group_ids=[group_ids["forest"]]).status_code == 413

    def test_a_vectors_read_error_is_an_error_not_a_zip(
        self, library, lancedb_service, monkeypatch
    ):
        client, _ids, group_ids, _ = library

        def broken(ids):
            raise OSError("disk read error")

        monkeypatch.setattr(lancedb_service, "get_vectors", broken)
        response = _download(client, group_ids=[group_ids["forest"]])
        assert response.status_code == 500
        assert response.headers["x-frame-options"] == "SAMEORIGIN"

    def test_other_responses_still_refuse_framing(self, library):
        client, ids, _group_ids, _ = library
        response = _download(client, image_ids=[ids["Loose"]])
        assert response.headers["x-frame-options"] == "DENY"

    def test_an_image_chosen_twice_is_in_the_zip_once(self, library):
        client, ids, group_ids, _ = library
        zf = _zip(_download(client, group_ids=[group_ids["forest"]], image_ids=[ids["Night"]]))
        assert len(zf.namelist()) == 3

    def test_a_name_that_isnt_ascii(self, library, tmp_db):
        client, _ids, group_ids, _ = library
        _engine, SessionLocal = tmp_db
        with SessionLocal() as db:
            db.get(ImageGroup, group_ids["cave"]).base_name = "Höhle des Drachen"
            db.commit()
        disposition = _download(client, group_ids=[group_ids["cave"]]).headers[
            "content-disposition"
        ]
        assert 'filename="AuthorA_H_hle des Drachen.zip"' in disposition
        assert "filename*=UTF-8''AuthorA_H%C3%B6hle%20des%20Drachen.zip" in disposition

    @pytest.mark.parametrize(
        "headers",
        [
            {"Sec-Fetch-Site": "cross-site"},
            {"Sec-Fetch-Site": "same-site"},
            {"Origin": "https://evil.example"},
        ],
    )
    def test_other_sites_are_refused(self, library, headers):
        client, ids, _group_ids, _ = library
        assert _download(client, image_ids=[ids["Loose"]], headers=headers).status_code == 403

    def test_the_apps_own_origin_is_allowed(self, library):
        client, ids, _group_ids, _ = library
        headers = {"Origin": "http://127.0.0.1:8000"}
        assert _download(client, image_ids=[ids["Loose"]], headers=headers).status_code == 200

    def test_a_request_from_no_browser_is_allowed(self, library):
        """No Sec-Fetch-Site and no Origin: not a browser (curl, a script). A browser sends
        Origin with every cross-origin POST, so this can't be another site's page."""
        client, ids, _group_ids, _ = library
        assert _download(client, image_ids=[ids["Loose"]], headers={}).status_code == 200

    def test_ids_must_be_numbers(self, library):
        client, _ids, _group_ids, _ = library
        response = client.post("/api/v1/downloads", data={"image_ids": "1,x"}, headers=SAME_SITE)
        assert response.status_code == 422


def test_a_single_image_downloads_under_its_readable_name(library):
    client, ids, _group_ids, store = library
    response = client.get(f"/api/v1/images/{ids['Night']}/file", params={"download": 1})
    assert response.status_code == 200
    assert response.headers["content-disposition"].startswith(
        'attachment; filename="AuthorA_Forest Map_Night_G20x15[winter].jpg"'
    )
    assert response.content == store.get_path("aa/bb/night.jpg").read_bytes()
    plain = client.get(f"/api/v1/images/{ids['Night']}/file")
    assert "content-disposition" not in plain.headers
