"""Shared fixtures for the test suite.

LanceDB is used as the vector database service. It does not create files on
import, so no pre-import patching is needed. We mock get_lancedb_service()
in fixtures where vector DB access is required.
"""

from pathlib import Path

import pytest
from PIL import Image as PILImage

from backend.app.models import (  # noqa: E402
    get_engine,
    get_session_local,
    init_db,
    seed_tag_categories,
)
from backend.app.services.prepare_pool import (  # noqa: E402
    init_prepare_pool,
    shutdown_prepare_pool,
)


@pytest.fixture(autouse=True)
def prepare_pool_fixture():
    """Initialize and clean up the prepare pool for each test."""
    shutdown_prepare_pool(wait=True)  # Ensure clean state
    init_prepare_pool(max_workers=2)  # Use small pool for tests
    yield
    shutdown_prepare_pool(wait=True)


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

    # Redirect database_url AND storage paths BEFORE entering TestClient so
    # that the lifespan (backfill, etc.) targets the test DB, not the
    # production one. The ingest worker is not started: tests drive it
    # synchronously with drain().
    orig_db_url = settings.database_url
    orig_images = settings.store_images_dir
    orig_thumbnails = settings.store_thumbnails_dir
    orig_staging = settings.staging_dir
    orig_worker_enabled = settings.ingest_worker_enabled
    settings.ingest_worker_enabled = False

    # The store singletons may already be cached at the real library path from
    # an earlier test; swap in stores rooted in tmp_path so nothing leaks into
    # the repo's images/ folder.
    from backend.app import services
    from backend.app.services.image_store import ImageStore

    orig_stores = (services._image_store, services._thumbnail_store)

    settings.database_url = str(engine.url)
    settings.store_images_dir = tmp_path / "store" / "images"
    settings.store_thumbnails_dir = tmp_path / "store" / "thumbnails"
    settings.staging_dir = tmp_path / "staging"
    settings.store_images_dir.mkdir(parents=True, exist_ok=True)
    services._image_store = ImageStore(settings.store_images_dir)
    services._thumbnail_store = ImageStore(settings.store_thumbnails_dir)
    settings.store_thumbnails_dir.mkdir(parents=True, exist_ok=True)
    settings.staging_dir.mkdir(parents=True, exist_ok=True)

    # Disable rate limiting during tests to prevent inter-test interference.
    from backend.app.api.rate_limits import limiter

    orig_limiter_enabled = limiter.enabled
    limiter.enabled = False

    try:
        with TestClient(app) as client:
            app.state.db_engine = engine
            yield client
    finally:
        # Restore original paths and rate limiter state
        limiter.enabled = orig_limiter_enabled
        settings.database_url = orig_db_url
        settings.store_images_dir = orig_images
        settings.store_thumbnails_dir = orig_thumbnails
        settings.staging_dir = orig_staging
        settings.ingest_worker_enabled = orig_worker_enabled
        services._image_store, services._thumbnail_store = orig_stores
