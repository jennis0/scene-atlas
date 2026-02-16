"""Shared fixtures for the test suite.

IMPORTANT: The QdrantService constructor tries to connect to Qdrant on import.
We mock QdrantClient before the qdrant_service module loads to prevent this.
"""

import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PIL import Image as PILImage

# ---------------------------------------------------------------------------
# Configure Prefect to use ephemeral in-memory server (no Docker/server needed).
# PREFECT_API_URL must be unset so Prefect doesn't try to reach a remote server.
# PREFECT_SERVER_ALLOW_EPHEMERAL_MODE lets flows run without a Prefect server.
# These must be set BEFORE any Prefect imports.
# ---------------------------------------------------------------------------
os.environ["PREFECT_SERVER_ALLOW_EPHEMERAL_MODE"] = "true"
os.environ["PREFECT_API_URL"] = ""

# Prefect's ephemeral server emits a harmless "Stopping temporary server"
# logging error during interpreter shutdown (after pytest closes stdout/stderr).
# This is a known Prefect issue — it doesn't affect test results.

# ---------------------------------------------------------------------------
# Mock QdrantClient BEFORE any backend.app.services imports.
# The qdrant_service module does `qdrant_service = QdrantService()` at module
# level, which calls QdrantClient(...) and ensure_collection(). We intercept
# QdrantClient to return a mock so no real connection is attempted.
# ---------------------------------------------------------------------------
_mock_qdrant_client_cls = MagicMock()
_mock_qdrant_client_instance = MagicMock()
_mock_qdrant_client_instance.get_collections.return_value = MagicMock(collections=[])
_mock_qdrant_client_cls.return_value = _mock_qdrant_client_instance

# Patch qdrant_client before it's imported by qdrant_service.py
import qdrant_client as _qc
_original_QdrantClient = _qc.QdrantClient
_qc.QdrantClient = _mock_qdrant_client_cls

# Also patch in the models submodule that qdrant_service imports from
import qdrant_client.models as _qc_models  # noqa: ensure it's loaded

# Now safe to import backend modules — QdrantService() will use the mock
from backend.app.models import get_engine, get_session_local, init_db, seed_tag_categories


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
    make_test_image(staging / "TestAuthor" / "TestMap" / "TestMap_Night_Grid.jpg", color=(30, 30, 80))
    make_test_image(staging / "TestAuthor" / "TestMap" / "TestMap_Summer.jpg", color=(100, 200, 100))
    make_test_image(staging / "FlatFile.jpg", color=(200, 100, 100))
    return staging


@pytest.fixture
def test_client(tmp_db):
    """FastAPI TestClient with test DB.

    The TestClient triggers the lifespan which sets app.state.db_engine
    to the production DB. We override it AFTER entering the context manager
    so our test DB takes precedence.
    """
    from fastapi.testclient import TestClient
    from backend.app.main import app

    engine, _ = tmp_db
    with TestClient(app, raise_server_exceptions=False) as client:
        app.state.db_engine = engine
        yield client


@pytest.fixture
def mock_heavy_services(monkeypatch):
    """Mock CLIP + Qdrant + thumbnails so integration tests don't need real infrastructure."""
    dummy_embedding = [0.1] * 512

    monkeypatch.setattr(
        "backend.flows.ingestion.generate_clip_embedding",
        lambda *args, **kwargs: dummy_embedding,
    )
    monkeypatch.setattr(
        "backend.flows.ingestion.qdrant_service.add_image_embedding",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        "backend.flows.ingestion.generate_thumbnails",
        lambda image_path, storage_key_stem: {
            "small": f"{storage_key_stem}_150x150.jpg",
            "medium": f"{storage_key_stem}_400x400.jpg",
            "large": f"{storage_key_stem}_800x800.jpg",
        },
    )
    monkeypatch.setattr(
        "backend.flows.ingestion.extract_dominant_colors",
        lambda *args, **kwargs: [
            {"color_hex": "#1a2b3c", "percentage": 40.0, "color_order": 1},
            {"color_hex": "#4d5e6f", "percentage": 30.0, "color_order": 2},
        ],
    )
    return dummy_embedding
