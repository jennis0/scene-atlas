"""Integration tests for system admin endpoints (library purge, tag reset)."""

import time

from backend.app.models.database import (
    Color,
    Image,
    ImageGroup,
    ImportGroup,
    ImportItem,
    ImportJob,
    Tag,
    TagCategory,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_library(db_session):
    """Seed a small library with images, groups, tags, and colors."""
    group = ImageGroup(base_name="Test Group", author="Author")
    db_session.add(group)
    db_session.flush()

    imgs = []
    for i in range(3):
        img = Image(
            name=f"Image {i}",
            filename=f"image_{i}.jpg",
            author="Author",
            storage_key=f"ab/cd/{i:08x}.jpg",
            thumbnail_key=f"ab/cd/{i:08x}_400x400.jpg",
            group_id=group.id,
            media_type="image",
            image_type="battlemap",
        )
        db_session.add(img)
        db_session.flush()
        imgs.append(img)

        db_session.add(
            Tag(
                image_id=img.id,
                category="lighting",
                value="night",
                confidence=0.9,
                source="auto",
            )
        )
        db_session.add(
            Color(
                image_id=img.id,
                color_hex="#1a2b3c",
                percentage=50.0,
                color_order=1,
            )
        )

    job = ImportJob(id="test-import-1", status="completed")
    db_session.add(job)
    db_session.flush()
    import_group = ImportGroup(job_id=job.id, group_name="Test Group", image_group_id=group.id)
    db_session.add(import_group)
    db_session.flush()
    for img in imgs:
        db_session.add(
            ImportItem(
                job_id=job.id,
                import_group_id=import_group.id,
                relative_path=img.filename,
                filename=img.filename,
                state="done",
                image_id=img.id,
            )
        )
    db_session.commit()

    return group.id, [img.id for img in imgs]


# ---------------------------------------------------------------------------
# DELETE /api/v1/system/library
# ---------------------------------------------------------------------------


class TestDeleteLibrary:
    def test_returns_job_id(self, test_client):
        resp = test_client.delete("/api/v1/system/library")
        assert resp.status_code == 200
        body = resp.json()
        assert "job_id" in body
        assert "message" in body

    def test_purge_clears_all_data(self, test_client, tmp_db):
        engine, SessionLocal = tmp_db
        db = SessionLocal()
        _seed_library(db)

        # Verify data exists
        assert db.query(Image).count() == 3
        assert db.query(ImageGroup).count() == 1
        assert db.query(Tag).count() == 3
        assert db.query(Color).count() == 3
        assert db.query(ImportJob).count() == 1
        assert db.query(ImportItem).count() == 3
        db.close()

        # Trigger purge
        resp = test_client.delete("/api/v1/system/library")
        assert resp.status_code == 200
        job_id = resp.json()["job_id"]

        # Poll until complete
        for _ in range(30):
            status_resp = test_client.get(f"/api/v1/jobs/{job_id}")
            if status_resp.json()["status"] in ("completed", "failed"):
                break
            time.sleep(0.2)

        assert status_resp.json()["status"] == "completed"

        # Verify everything is cleared
        db = SessionLocal()
        assert db.query(Image).count() == 0
        assert db.query(ImageGroup).count() == 0
        assert db.query(Tag).count() == 0
        assert db.query(Color).count() == 0
        assert db.query(ImportJob).count() == 0
        assert db.query(ImportItem).count() == 0
        assert db.query(ImportGroup).count() == 0
        db.close()

    def test_purge_preserves_tag_categories(self, test_client, tmp_db):
        """Purging the library should NOT delete tag categories."""
        engine, SessionLocal = tmp_db
        db = SessionLocal()
        _seed_library(db)
        cats_before = db.query(TagCategory).count()
        assert cats_before > 0
        db.close()

        resp = test_client.delete("/api/v1/system/library")
        job_id = resp.json()["job_id"]

        for _ in range(30):
            status_resp = test_client.get(f"/api/v1/jobs/{job_id}")
            if status_resp.json()["status"] in ("completed", "failed"):
                break
            time.sleep(0.2)

        db = SessionLocal()
        assert db.query(TagCategory).count() == cats_before
        db.close()


# ---------------------------------------------------------------------------
# POST /api/v1/system/tags/reset
# ---------------------------------------------------------------------------


class TestResetTags:
    def test_clears_all_tags(self, test_client, tmp_db):
        engine, SessionLocal = tmp_db
        db = SessionLocal()
        _seed_library(db)
        assert db.query(Tag).count() > 0
        db.close()

        resp = test_client.post("/api/v1/system/tags/reset")
        assert resp.status_code == 200
        body = resp.json()
        assert body["deleted_tags"] == 3

        db = SessionLocal()
        assert db.query(Tag).count() == 0
        db.close()

    def test_reseeds_categories(self, test_client, tmp_db):
        engine, SessionLocal = tmp_db

        resp = test_client.post("/api/v1/system/tags/reset")
        assert resp.status_code == 200
        body = resp.json()
        assert body["seeded_categories"] > 0

        # Verify categories exist
        db = SessionLocal()
        assert db.query(TagCategory).count() == body["seeded_categories"]
        db.close()

    def test_returns_correct_counts(self, test_client, tmp_db):
        engine, SessionLocal = tmp_db
        db = SessionLocal()
        _seed_library(db)

        cats_before = db.query(TagCategory).count()
        tags_before = db.query(Tag).count()
        db.close()

        resp = test_client.post("/api/v1/system/tags/reset")
        body = resp.json()

        assert body["deleted_tags"] == tags_before
        assert body["deleted_categories"] == cats_before
        assert body["seeded_categories"] > 0

    def test_images_preserved_after_tag_reset(self, test_client, tmp_db):
        """Resetting tags should not delete images or groups."""
        engine, SessionLocal = tmp_db
        db = SessionLocal()
        _seed_library(db)
        img_count = db.query(Image).count()
        group_count = db.query(ImageGroup).count()
        db.close()

        test_client.post("/api/v1/system/tags/reset")

        db = SessionLocal()
        assert db.query(Image).count() == img_count
        assert db.query(ImageGroup).count() == group_count
        db.close()
