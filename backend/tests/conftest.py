"""Shared fixtures for the test suite.

IMPORTANT: QdrantService uses a lazy singleton (get_qdrant_service()), but it
still gets constructed on first call. We mock QdrantClient before any backend
imports to prevent the embedded Qdrant DB from being created during tests.
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PIL import Image as PILImage

# ---------------------------------------------------------------------------
# Mock QdrantClient BEFORE any backend.app.services imports.
# QdrantService.__init__ calls QdrantClient(path=...) which creates a local
# DB on disk. We intercept QdrantClient to return a mock so no real DB is
# created during tests.
# ---------------------------------------------------------------------------
_mock_qdrant_client_cls = MagicMock()
_mock_qdrant_client_instance = MagicMock()
_mock_qdrant_client_instance.get_collections.return_value = MagicMock(collections=[])
_mock_qdrant_client_cls.return_value = _mock_qdrant_client_instance

# Patch qdrant_client before it's imported by qdrant_service.py
import qdrant_client as _qc  # noqa: E402

_qc.QdrantClient = _mock_qdrant_client_cls

# Now safe to import backend modules — QdrantService() will use the mock
from backend.app.models import (  # noqa: E402
    get_engine,
    get_session_local,
    init_db,
    seed_tag_categories,
)


@pytest.fixture
def tmp_db(tmp_path):
    """Fresh SQLite DB seeded with tag categories."""
    db_url = f"sqlite:///{tmp_path}/test.db"
    engine = get_engine(db_url)
    init_db(engine)
    SessionLocal = get_session_local(engine)
    db = SessionLocal()
    seed_tag_categories(db)
    db.close()
    yield engine, SessionLocal
    engine.dispose()


@pytest.fixture
def db_session(tmp_db):
    """Yield a DB session from the test database, closes after use."""
    engine, SessionLocal = tmp_db
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def make_test_image():
    """Factory fixture that creates minimal test JPEG files."""

    def _make(path: Path, width: int = 20, height: int = 20, color: tuple = (100, 150, 200)):
        path.parent.mkdir(parents=True, exist_ok=True)
        img = PILImage.new("RGB", (width, height), color)
        img.save(path, format="JPEG", quality=70)
        return path

    return _make


@pytest.fixture
def tmp_staging(tmp_path, make_test_image):
    """Staging directory with programmatically generated test images."""
    staging = tmp_path / "staging" / "test-job-id"
    make_test_image(
        staging / "TestAuthor" / "TestMap" / "TestMap_Night_Grid.jpg", color=(30, 30, 80)
    )
    make_test_image(
        staging / "TestAuthor" / "TestMap" / "TestMap_Summer.jpg", color=(100, 200, 100)
    )
    make_test_image(staging / "FlatFile.jpg", color=(200, 100, 100))
    return staging


@pytest.fixture
def test_client(tmp_db, tmp_path):
    """FastAPI TestClient with test DB and isolated storage paths.

    The TestClient triggers the lifespan which sets app.state.db_engine
    to the production DB. We override it AFTER entering the context manager
    so our test DB takes precedence.

    CRITICAL: We also redirect settings storage paths to temp directories
    so that tests like purge_library (which call shutil.rmtree on
    settings.store_images_dir) never touch production files.
    """
    from fastapi.testclient import TestClient

    from backend.app.config import settings
    from backend.app.main import app

    engine, _ = tmp_db

    # Redirect all storage paths to temp directories
    orig_images = settings.store_images_dir
    orig_thumbnails = settings.store_thumbnails_dir
    orig_staging = settings.staging_dir

    settings.store_images_dir = tmp_path / "store" / "images"
    settings.store_thumbnails_dir = tmp_path / "store" / "thumbnails"
    settings.staging_dir = tmp_path / "staging"
    settings.store_images_dir.mkdir(parents=True, exist_ok=True)
    settings.store_thumbnails_dir.mkdir(parents=True, exist_ok=True)
    settings.staging_dir.mkdir(parents=True, exist_ok=True)

    try:
        with TestClient(app) as client:
            app.state.db_engine = engine
            yield client
    finally:
        # Restore original paths
        settings.store_images_dir = orig_images
        settings.store_thumbnails_dir = orig_thumbnails
        settings.staging_dir = orig_staging


@pytest.fixture
def mock_heavy_services(monkeypatch):
    """Mock CLIP + Qdrant + thumbnails so integration tests don't need real infrastructure.

    The batch pipeline calls task functions via .fn() from their source modules,
    so we mock at the source (backend.pipeline.tasks.*) not at the ingestion module level.
    """
    dummy_embedding = [0.1] * 512

    # Mock single-image CLIP (used by process_single_image wrapper)
    monkeypatch.setattr(
        "backend.pipeline.ingestion.generate_clip_embedding",
        lambda *args, **kwargs: dummy_embedding,
    )
    # Mock batch CLIP (used by batch pipeline)
    monkeypatch.setattr(
        "backend.pipeline.ingestion.batch_generate_clip_embeddings",
        lambda image_paths, **kwargs: [dummy_embedding] * len(image_paths),
    )

    # Mock Qdrant (single + batch) — get_qdrant_service() returns a mock
    mock_qdrant_svc = MagicMock()
    mock_qdrant_svc.add_image_embedding.return_value = True
    mock_qdrant_svc.batch_add_embeddings.return_value = True
    mock_qdrant_svc.get_embedding.return_value = None
    monkeypatch.setattr(
        "backend.pipeline.ingestion.get_qdrant_service",
        lambda: mock_qdrant_svc,
    )

    # Mock thumbnails at the source module
    def mock_generate_thumbnails(image_path, storage_key_stem):
        # Open image to get real dimensions (needed for DB save)
        from PIL import Image as PILImage

        with PILImage.open(image_path) as img:
            dimensions = img.size
        return {
            "keys": {
                "small": f"{storage_key_stem}_150x150.jpg",
                "medium": f"{storage_key_stem}_400x400.jpg",
                "large": f"{storage_key_stem}_800x800.jpg",
            },
            "dimensions": dimensions,
        }

    monkeypatch.setattr(
        "backend.pipeline.tasks.image_processing.generate_thumbnails",
        mock_generate_thumbnails,
    )

    # Mock color extraction at source module
    def mock_extract_colors(*args, **kwargs):
        return [
            {"color_hex": "#1a2b3c", "percentage": 40.0, "color_order": 1},
            {"color_hex": "#4d5e6f", "percentage": 30.0, "color_order": 2},
        ]

    monkeypatch.setattr(
        "backend.pipeline.tasks.color_extraction.extract_dominant_colors",
        mock_extract_colors,
    )

    return dummy_embedding
