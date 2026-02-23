"""Integration tests for the images API endpoints (/api/v1/images/)."""

from unittest.mock import MagicMock

import pytest

from backend.app.models.database import Image, ImageGroup

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _add_image(db, name, storage_key, **kwargs):
    defaults = {
        "filename": f"{name}.jpg",
        "author": "TestAuthor",
        "image_type": "battlemap",
        "media_type": "image",
    }
    defaults.update(kwargs)
    img = Image(name=name, storage_key=storage_key, **defaults)
    db.add(img)
    db.flush()
    return img


@pytest.fixture
def images_db(test_client, tmp_db):
    """Seed images and return (client, image_ids_dict)."""
    engine, SessionLocal = tmp_db
    db = SessionLocal()

    g = ImageGroup(base_name="Forest Map", author="TestAuthor")
    db.add(g)
    db.flush()

    img1 = _add_image(
        db,
        "Forest Map Night",
        "ab/cd/img1.jpg",
        author="AuthorA",
        group_id=g.id,
        gridded=True,
        grid_width=20,
        grid_height=15,
    )
    img2 = _add_image(db, "Forest Map Day", "ab/cd/img2.jpg", author="AuthorA", group_id=g.id)
    img3 = _add_image(db, "Cave Map", "ef/gh/img3.jpg", author="AuthorB")

    db.commit()
    ids = {"img1": img1.id, "img2": img2.id, "img3": img3.id}
    db.close()
    yield test_client, ids


# ---------------------------------------------------------------------------
# GET /api/v1/images/authors
# ---------------------------------------------------------------------------


class TestListAuthors:
    def test_returns_sorted_authors(self, images_db):
        client, _ = images_db
        resp = client.get("/api/v1/images/authors")
        assert resp.status_code == 200
        authors = resp.json()
        assert authors == sorted(authors)
        assert "AuthorA" in authors
        assert "AuthorB" in authors


# ---------------------------------------------------------------------------
# GET /api/v1/images/
# ---------------------------------------------------------------------------


class TestListImages:
    def test_default_returns_all(self, images_db):
        client, ids = images_db
        resp = client.get("/api/v1/images/")
        assert resp.status_code == 200
        assert len(resp.json()) == len(ids)

    def test_pagination(self, images_db):
        client, _ = images_db
        resp = client.get("/api/v1/images/", params={"limit": 1})
        assert len(resp.json()) == 1

    def test_skip(self, images_db):
        client, ids = images_db
        resp = client.get("/api/v1/images/", params={"skip": 100})
        assert len(resp.json()) == 0


# ---------------------------------------------------------------------------
# GET /api/v1/images/{id}
# ---------------------------------------------------------------------------


class TestGetImage:
    def test_existing_image(self, images_db):
        client, ids = images_db
        resp = client.get(f"/api/v1/images/{ids['img1']}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Forest Map Night"
        assert data["author"] == "AuthorA"

    def test_nonexistent_404(self, images_db):
        client, _ = images_db
        resp = client.get("/api/v1/images/99999")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /api/v1/images/{id}
# ---------------------------------------------------------------------------


class TestPatchImage:
    def test_update_name(self, images_db):
        client, ids = images_db
        resp = client.patch(f"/api/v1/images/{ids['img1']}", json={"name": "Renamed"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "Renamed"

    def test_update_grid_info(self, images_db):
        client, ids = images_db
        resp = client.patch(
            f"/api/v1/images/{ids['img3']}",
            json={"gridded": True, "grid_width": 30, "grid_height": 20, "grid_type": "square"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["gridded"] is True
        assert data["grid_width"] == 30

    def test_update_image_type(self, images_db):
        client, ids = images_db
        resp = client.patch(f"/api/v1/images/{ids['img1']}", json={"image_type": "scene"})
        assert resp.status_code == 200
        assert resp.json()["image_type"] == "scene"

    def test_nonexistent_404(self, images_db):
        client, _ = images_db
        resp = client.patch("/api/v1/images/99999", json={"name": "X"})
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/v1/images/{id}
# ---------------------------------------------------------------------------


class TestDeleteImage:
    def test_delete_removes_image(self, images_db, monkeypatch):
        client, ids = images_db
        # Mock safe_delete_image since we don't have real files
        monkeypatch.setattr(
            "backend.app.api.images.safe_delete_image",
            lambda db, img: db.delete(img),
        )
        resp = client.delete(f"/api/v1/images/{ids['img3']}")
        assert resp.status_code == 200

        # Verify deleted
        resp2 = client.get(f"/api/v1/images/{ids['img3']}")
        assert resp2.status_code == 404

    def test_nonexistent_404(self, images_db):
        client, _ = images_db
        resp = client.delete("/api/v1/images/99999")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/v1/images/{id}/scenes
# ---------------------------------------------------------------------------


class TestGetImageScenes:
    def test_grouped_image_returns_all_in_group(self, images_db):
        client, ids = images_db
        resp = client.get(f"/api/v1/images/{ids['img1']}/scenes")
        assert resp.status_code == 200
        scene_ids = {s["id"] for s in resp.json()}
        assert ids["img1"] in scene_ids
        assert ids["img2"] in scene_ids
        assert ids["img3"] not in scene_ids

    def test_ungrouped_image_returns_self(self, images_db):
        client, ids = images_db
        resp = client.get(f"/api/v1/images/{ids['img3']}/scenes")
        assert resp.status_code == 200
        scenes = resp.json()
        assert len(scenes) == 1
        assert scenes[0]["id"] == ids["img3"]

    def test_nonexistent_404(self, images_db):
        client, _ = images_db
        resp = client.get("/api/v1/images/99999/scenes")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/v1/images/{id}/file
# ---------------------------------------------------------------------------


class TestGetImageFile:
    def test_serves_file(self, images_db, make_test_image, tmp_path, monkeypatch):
        client, ids = images_db

        # Create a real file and mock the image store
        real_file = tmp_path / "real.jpg"
        make_test_image(real_file)

        from backend.app.services.image_store import ImageStore

        store = ImageStore(tmp_path / "store")
        # Put the file into the store at the expected key
        dest = store.get_path("ab/cd/img1.jpg")
        dest.parent.mkdir(parents=True, exist_ok=True)
        real_file.rename(dest)

        monkeypatch.setattr("backend.app.api.images.get_image_store", lambda: store)

        resp = client.get(f"/api/v1/images/{ids['img1']}/file")
        assert resp.status_code == 200

    def test_missing_file_404(self, images_db, monkeypatch, tmp_path):
        client, ids = images_db
        from backend.app.services.image_store import ImageStore

        store = ImageStore(tmp_path / "empty_store")
        monkeypatch.setattr("backend.app.api.images.get_image_store", lambda: store)

        resp = client.get(f"/api/v1/images/{ids['img1']}/file")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/v1/images/backfill-grids
# ---------------------------------------------------------------------------


class TestTriggerBackfillGrids:
    def test_submits_job(self, images_db, monkeypatch):
        client, _ = images_db
        mock_runner = MagicMock()
        mock_runner.submit.return_value = "job-123"
        monkeypatch.setattr(
            "backend.app.services.job_runner.get_job_runner",
            lambda: mock_runner,
        )
        resp = client.post("/api/v1/images/backfill-grids")
        assert resp.status_code == 200
        assert resp.json()["job_id"] == "job-123"

    def test_returns_503_on_failure(self, images_db, monkeypatch):
        client, _ = images_db
        mock_runner = MagicMock()
        mock_runner.submit.side_effect = RuntimeError("no workers")
        monkeypatch.setattr(
            "backend.app.services.job_runner.get_job_runner",
            lambda: mock_runner,
        )
        resp = client.post("/api/v1/images/backfill-grids")
        assert resp.status_code == 503
