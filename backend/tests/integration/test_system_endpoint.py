"""Integration tests for GET /api/v1/system/info.

Uses the shared test_client + tmp_db fixtures to verify the endpoint returns
correct response shape and library counts from a real SQLite database.
"""

from backend.app.models.database import Image, ImageGroup


def _add_image(db, name: str, **kwargs) -> Image:
    img = Image(
        name=name,
        filename=f"{name}.jpg",
        author=kwargs.get("author", "TestAuthor"),
        storage_key=f"{name.lower()}.jpg",
        image_type="battlemap",
        media_type="image",
    )
    db.add(img)
    db.flush()
    return img


def _add_group(db, base_name: str) -> ImageGroup:
    group = ImageGroup(base_name=base_name)
    db.add(group)
    db.flush()
    return group


class TestSystemInfoEndpoint:
    def test_returns_200(self, test_client):
        resp = test_client.get("/api/v1/system/info")
        assert resp.status_code == 200

    def test_response_top_level_keys(self, test_client):
        data = test_client.get("/api/v1/system/info").json()
        assert "mode" in data
        assert "storage" in data
        assert "library" in data
        # storage_path is only included in app (desktop) mode, not server mode
        assert "storage_path" not in data

    def test_mode_field_is_server_by_default(self, test_client):
        data = test_client.get("/api/v1/system/info").json()
        assert data["mode"] == "server"

    def test_storage_shape(self, test_client):
        storage = test_client.get("/api/v1/system/info").json()["storage"]
        for key in ("images_bytes", "vectors_bytes", "metadata_bytes", "total_bytes"):
            assert key in storage
            assert isinstance(storage[key], int)

    def test_library_counts(self, test_client, tmp_db):
        """Seed images and a group, verify the counts match."""
        engine, SessionLocal = tmp_db
        db = SessionLocal()
        try:
            _add_group(db, "Test Group")
            _add_image(db, "Image1")
            _add_image(db, "Image2")
            _add_image(db, "Image3")
            db.commit()
        finally:
            db.close()

        data = test_client.get("/api/v1/system/info").json()
        assert data["library"]["image_count"] == 3
        assert data["library"]["group_count"] == 1

    def test_library_counts_empty(self, test_client):
        """Empty library should report zero counts."""
        data = test_client.get("/api/v1/system/info").json()
        assert data["library"]["image_count"] == 0
        assert data["library"]["group_count"] == 0
