"""Integration tests for the export API endpoint (/api/v1/export/library)."""

import json
import zipfile
from io import BytesIO

import pytest

from backend.app.models.database import Image, ImageGroup, Tag
from backend.app.services.image_store import ImageStore

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _seed_library(db, image_store, make_test_image, tmp_path):
    """Seed a small library with real files in the image store."""
    g = ImageGroup(base_name="Forest Map", author="AuthorA")
    db.add(g)
    db.flush()

    images = []
    for name, key, group_id, gridded, gw, gh in [
        ("Forest Night", "aa/bb/img1.jpg", g.id, True, 20, 15),
        ("Forest Day", "aa/bb/img2.jpg", g.id, False, None, None),
        ("Cave Map", "cc/dd/img3.jpg", None, False, None, None),
    ]:
        img = Image(
            name=name,
            filename=f"{name.replace(' ', '_')}.jpg",
            author="AuthorA",
            storage_key=key,
            image_type="battlemap",
            media_type="image",
            group_id=group_id,
            gridded=gridded,
            grid_width=gw,
            grid_height=gh,
        )
        db.add(img)
        db.flush()

        # Create real file in the image store
        file_path = image_store.get_path(key)
        make_test_image(file_path, width=100, height=100)

        images.append(img)

    # Add a tag to first image
    db.add(
        Tag(
            image_id=images[0].id, category="terrain", value="forest", confidence=1.0, source="auto"
        )
    )

    db.commit()
    return [img.id for img in images]


@pytest.fixture
def export_lib(test_client, tmp_db, make_test_image, tmp_path, monkeypatch):
    """Seed library with real files and return the test client."""
    engine, SessionLocal = tmp_db
    db = SessionLocal()

    store = ImageStore(tmp_path / "image_store")

    # Originals are read through services.originals, which uses the package getter
    monkeypatch.setattr("backend.app.services.get_image_store", lambda: store)

    ids = _seed_library(db, store, make_test_image, tmp_path)
    db.close()

    yield test_client, ids


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestExportLibrary:
    def test_returns_zip(self, export_lib):
        client, _ = export_lib
        resp = client.get("/api/v1/export/library")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/zip"

    def test_zip_contains_metadata_json(self, export_lib):
        client, _ = export_lib
        resp = client.get("/api/v1/export/library")
        buf = BytesIO(resp.content)
        with zipfile.ZipFile(buf) as zf:
            assert "metadata.json" in zf.namelist()
            meta = json.loads(zf.read("metadata.json"))
            assert "exported_at" in meta
            assert "version" in meta
            assert meta["total_images"] == 3

    def test_zip_contains_image_files(self, export_lib):
        client, _ = export_lib
        resp = client.get("/api/v1/export/library")
        buf = BytesIO(resp.content)
        with zipfile.ZipFile(buf) as zf:
            names = zf.namelist()
            # metadata.json + 3 images
            assert len(names) == 4
            image_names = [n for n in names if n != "metadata.json"]
            assert len(image_names) == 3

    def test_zip_paths_follow_structure(self, export_lib):
        client, _ = export_lib
        resp = client.get("/api/v1/export/library")
        buf = BytesIO(resp.content)
        with zipfile.ZipFile(buf) as zf:
            image_names = [n for n in zf.namelist() if n != "metadata.json"]
            # Grouped images go under Author/Group/
            grouped = [n for n in image_names if "/Forest Map/" in n]
            assert len(grouped) == 2
            # Ungrouped image goes under Author/_Ungrouped/
            ungrouped = [n for n in image_names if "/_Ungrouped/" in n]
            assert len(ungrouped) == 1

    def test_metadata_includes_tags(self, export_lib):
        client, _ = export_lib
        resp = client.get("/api/v1/export/library")
        buf = BytesIO(resp.content)
        with zipfile.ZipFile(buf) as zf:
            meta = json.loads(zf.read("metadata.json"))
            # At least one image should have terrain: forest
            has_terrain = any(
                "terrain" in img_meta.get("tags", {}) for img_meta in meta["images"].values()
            )
            assert has_terrain

    def test_content_length_header_set(self, export_lib):
        client, _ = export_lib
        resp = client.get("/api/v1/export/library")
        assert "content-length" in resp.headers
        cl = int(resp.headers["content-length"])
        assert cl > 0

    def test_content_disposition_header(self, export_lib):
        client, _ = export_lib
        resp = client.get("/api/v1/export/library")
        assert "Scene Atlas Export.zip" in resp.headers.get("content-disposition", "")
