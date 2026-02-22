"""Integration test: process_single_image flow (direct call).

Tests both modes:
- With explicit metadata (web import path)
- With source_dir (CLI import path, uses parser)

Uses real DB + real filesystem. Mocks CLIP, Qdrant, thumbnails.
"""


import pytest

from backend.app.models import Image


@pytest.fixture
def _patch_db_for_flows(monkeypatch, tmp_db):
    engine, SessionLocal = tmp_db
    db_url = str(engine.url)
    monkeypatch.setattr("backend.app.config.settings.database_url", db_url)
    return engine, SessionLocal


@pytest.fixture
def _patch_image_store(monkeypatch, tmp_path):
    from backend.app.services.image_store import ImageStore

    store = ImageStore(tmp_path / "store")
    monkeypatch.setattr("backend.flows.ingestion.get_image_store", lambda: store)
    return store


class TestProcessSingleImageWithMetadata:
    """Web import mode: explicit metadata dict, no parsing."""

    def test_success_with_metadata(
        self,
        tmp_staging,
        mock_heavy_services,
        _patch_db_for_flows,
        _patch_image_store,
    ):
        from backend.flows.ingestion import process_single_image

        engine, SessionLocal = _patch_db_for_flows
        image_path = tmp_staging / "TestAuthor" / "TestMap" / "TestMap_Summer.jpg"

        result = process_single_image(
            image_path=str(image_path),
            metadata={
                "author": "ExplicitAuthor",
                "group_name": "Explicit Group",
                "tags": [
                    {"category": "season", "value": "summer", "confidence": 0.9, "source": "auto"}
                ],
                "gridded": None,
                "grid_width": None,
                "grid_height": None,
                "subgroup": "Summer",
            },
        )

        assert result["status"] == "success"

        db = SessionLocal()
        try:
            image = db.query(Image).filter(Image.id == result["image_id"]).first()
            assert image.author == "ExplicitAuthor"
            assert image.name == "Explicit Group"
            assert image.subgroup == "Summer"
        finally:
            db.close()


class TestProcessSingleImageWithSourceDir:
    """CLI import mode: parse metadata from path."""

    def test_success_with_source_dir(
        self,
        tmp_staging,
        mock_heavy_services,
        _patch_db_for_flows,
        _patch_image_store,
    ):
        from backend.flows.ingestion import process_single_image

        engine, SessionLocal = _patch_db_for_flows
        image_path = tmp_staging / "TestAuthor" / "TestMap" / "TestMap_Night_Grid.jpg"

        result = process_single_image(
            image_path=str(image_path),
            source_dir=str(tmp_staging),
        )

        assert result["status"] == "success"

        db = SessionLocal()
        try:
            image = db.query(Image).filter(Image.id == result["image_id"]).first()
            assert image.author == "TestAuthor"
            assert image.gridded is True
        finally:
            db.close()


class TestProcessSingleImageStoresFile:
    """Image is stored in ImageStore after processing."""

    def test_file_stored(
        self,
        tmp_staging,
        mock_heavy_services,
        _patch_db_for_flows,
        _patch_image_store,
    ):
        from backend.flows.ingestion import process_single_image

        store = _patch_image_store
        image_path = tmp_staging / "FlatFile.jpg"

        result = process_single_image(
            image_path=str(image_path),
            metadata={
                "author": "A",
                "group_name": "G",
                "tags": [],
                "gridded": None,
                "grid_width": None,
                "grid_height": None,
                "subgroup": None,
            },
        )

        assert result["status"] == "success"

        engine, SessionLocal = _patch_db_for_flows
        db = SessionLocal()
        try:
            image = db.query(Image).filter(Image.id == result["image_id"]).first()
            assert store.exists(image.storage_key)
        finally:
            db.close()
