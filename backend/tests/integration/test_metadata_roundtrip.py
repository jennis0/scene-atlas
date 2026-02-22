"""Integration test: user-edited metadata survives the full round-trip to DB.

This is THE critical test for the import refactor. When a user edits metadata
in the preview UI (adds a custom tag, overrides gridded, etc.), those edits
must arrive in the database unchanged — the backend must NOT re-parse and
silently overwrite them.

Requires: real DB (SQLite in tmp_path). Mocks: CLIP, Qdrant, thumbnails, ImageStore.
"""


import pytest

from backend.app.models import Image, ImageGroup, Tag


@pytest.fixture
def _patch_db_for_flows(monkeypatch, tmp_db):
    """Make the flow's save_to_database use our test DB instead of settings.database_url."""
    engine, SessionLocal = tmp_db
    db_url = str(engine.url)
    monkeypatch.setattr("backend.app.config.settings.database_url", db_url)
    return engine, SessionLocal


@pytest.fixture
def _patch_image_store(monkeypatch, tmp_path):
    """Point ImageStore at a temp directory."""
    from backend.app.services.image_store import ImageStore

    store = ImageStore(tmp_path / "store")
    monkeypatch.setattr("backend.flows.ingestion.get_image_store", lambda: store)
    return store


class TestMetadataRoundTrip:
    """User-provided metadata must arrive in DB unchanged."""

    def test_custom_tag_survives(
        self,
        tmp_staging,
        mock_heavy_services,
        _patch_db_for_flows,
        _patch_image_store,
    ):
        """A user-added tag that the parser would never produce must persist."""
        from backend.flows.ingestion import process_single_image

        engine, SessionLocal = _patch_db_for_flows
        image_path = tmp_staging / "TestAuthor" / "TestMap" / "TestMap_Night_Grid.jpg"

        result = process_single_image(
            image_path=str(image_path),
            metadata={
                "author": "CustomAuthor",
                "group_name": "Custom Group",
                "tags": [
                    {
                        "category": "custom",
                        "value": "user-added",
                        "confidence": 1.0,
                        "source": "manual",
                    },
                    {"category": "lighting", "value": "night", "confidence": 0.9, "source": "auto"},
                ],
                "gridded": True,
                "grid_width": 30,
                "grid_height": 30,
                "subgroup": "Night",
            },
        )

        assert result["status"] == "success"
        image_id = result["image_id"]

        # Verify in DB
        db = SessionLocal()
        try:
            image = db.query(Image).filter(Image.id == image_id).first()
            assert image is not None
            assert image.author == "CustomAuthor"
            assert image.gridded is True
            assert image.grid_width == 30
            assert image.grid_height == 30
            assert image.subgroup == "Night"

            tags = db.query(Tag).filter(Tag.image_id == image_id).all()
            tag_set = {(t.category, t.value) for t in tags}
            assert ("custom", "user-added") in tag_set
            assert ("lighting", "night") in tag_set

            # Verify group
            grp = db.query(ImageGroup).filter(ImageGroup.id == image.group_id).first()
            assert grp is not None
            assert grp.base_name == "Custom Group"
            assert grp.author == "CustomAuthor"
        finally:
            db.close()

    def test_gridded_override_persists(
        self,
        tmp_staging,
        mock_heavy_services,
        _patch_db_for_flows,
        _patch_image_store,
    ):
        """User sets gridded=True on a file that the parser would say is None."""
        from backend.flows.ingestion import process_single_image

        engine, SessionLocal = _patch_db_for_flows
        # This file has no grid indicator in its name
        image_path = tmp_staging / "TestAuthor" / "TestMap" / "TestMap_Summer.jpg"

        result = process_single_image(
            image_path=str(image_path),
            metadata={
                "author": "TestAuthor",
                "group_name": "TestMap",
                "tags": [],
                "gridded": True,
                "grid_width": 25,
                "grid_height": 25,
                "subgroup": None,
            },
        )

        assert result["status"] == "success"

        db = SessionLocal()
        try:
            image = db.query(Image).filter(Image.id == result["image_id"]).first()
            assert image.gridded is True
            assert image.grid_width == 25
            assert image.grid_height == 25
        finally:
            db.close()

    def test_process_import_group_passes_metadata_through(
        self,
        tmp_staging,
        mock_heavy_services,
        _patch_db_for_flows,
        _patch_image_store,
    ):
        """process_import_group should relay per-file metadata to process_single_image."""
        from backend.app.models import ImportJob
        from backend.flows.ingestion import process_import_group

        engine, SessionLocal = _patch_db_for_flows

        # Create an ImportJob + ImportGroupJob so progress updates don't fail
        db = SessionLocal()
        job = ImportJob(id="test-roundtrip-job", status="running", total_files=1)
        db.add(job)
        from backend.app.models import ImportGroupJob
        group_job = ImportGroupJob(
            id="test-roundtrip-group",
            job_id="test-roundtrip-job",
            group_name="Roundtrip Group",
            author="RoundtripAuthor",
            total_files=1,
            processed_files=0,
            failed_files=0,
            status="running",
        )
        db.add(group_job)
        db.commit()
        db.close()

        result = process_import_group(
            job_id="test-roundtrip-job",
            group_job_id="test-roundtrip-group",
            staging_dir=str(tmp_staging),
            author="RoundtripAuthor",
            group_name="Roundtrip Group",
            files=[
                {
                    "relative_path": "TestAuthor/TestMap/TestMap_Night_Grid.jpg",
                    "tags": [
                        {
                            "category": "mood",
                            "value": "spooky",
                            "confidence": 1.0,
                            "source": "manual",
                        }
                    ],
                    "gridded": False,
                    "grid_width": None,
                    "grid_height": None,
                    "subgroup": "Spooky Night",
                },
            ],
        )

        assert result["processed"] == 1
        assert result["failed"] == 0

        db = SessionLocal()
        try:
            images = db.query(Image).filter(Image.author == "RoundtripAuthor").all()
            assert len(images) == 1
            img = images[0]
            assert img.gridded is False
            assert img.subgroup == "Spooky Night"

            tags = db.query(Tag).filter(Tag.image_id == img.id).all()
            assert any(t.category == "mood" and t.value == "spooky" for t in tags)
        finally:
            db.close()
