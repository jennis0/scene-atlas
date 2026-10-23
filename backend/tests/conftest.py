"""Shared fixtures for the test suite.

LanceDB does not create files on import, so no pre-import patching is needed.
Tests that touch vectors use the ``lancedb_service`` fixture (a real LanceDB in
``tmp_path``); pure unit tests may still fake ``get_lancedb_service()``.
"""

import atexit
import os
import shutil
import tempfile
from pathlib import Path

# Point every storage root at a throwaway directory before any backend module builds
# its Settings. Otherwise app startup (TestClient lifespan) migrates and writes to the
# developer's real ./data library.
_TEST_ROOT = Path(tempfile.mkdtemp(prefix="scene-atlas-tests-"))
os.environ["SCENE_ATLAS_DATA_DIR"] = str(_TEST_ROOT / "data")
os.environ["SCENE_ATLAS_IMAGES_DIR"] = str(_TEST_ROOT / "images")
atexit.register(shutil.rmtree, _TEST_ROOT, ignore_errors=True)
# Tests never contact GitHub; the update checker's own tests inject a fake fetcher.
os.environ["SCENE_ATLAS_CHECK_FOR_UPDATES"] = "false"

import pytest
from PIL import Image as PILImage

from backend.app.models import (
    get_engine,
    get_session_local,
    init_db,
    seed_tag_categories,
)
from backend.app.services.prepare_pool import (
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


@pytest.fixture(autouse=True)
def shutdown_signal_cleared():
    """A TestClient exit runs the lifespan shutdown, which sets the process-wide signal."""
    from backend.app.services.shutdown import clear_shutdown

    clear_shutdown()
    yield
    clear_shutdown()


@pytest.fixture(autouse=True)
def grouping_inline(monkeypatch):
    """An import's grouping phase (ADR-028) runs synchronously where it is scheduled, never
    on the JobRunner's threads, and without embeddings (no model in tests). Tests that need
    another readiness install their own scheduler."""
    from backend.pipeline import group_jobs

    scheduler = group_jobs.GroupingScheduler.inline(lambda: group_jobs.Readiness.OFF)
    monkeypatch.setattr(group_jobs, "_scheduler", scheduler)
    return scheduler


@pytest.fixture
def no_grouping(monkeypatch):
    """No grouping phase at all: jobs stay ``grouping`` (tests of that state, and tests
    counting a batch's queries)."""
    from backend.pipeline import group_jobs

    class _Off(group_jobs.GroupingScheduler):
        def schedule(self, job_ids=None):
            return []

    monkeypatch.setattr(group_jobs, "_scheduler", _Off())


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


TEST_VECTOR_SIZE = 8


@pytest.fixture
def lancedb_service(tmp_path, monkeypatch):
    """A real LanceDB under ``tmp_path``, returned by every ``get_lancedb_service()``.

    Swaps the module singleton rather than patching import sites, so code that
    imported the getter by name sees it too. Vectors are ``TEST_VECTOR_SIZE`` wide.
    """
    from backend.app.services import lancedb_service as module

    svc = module.LanceDBService(
        path=tmp_path / "lancedb",
        collection_name="test_embeddings",
        vector_size=TEST_VECTOR_SIZE,
    )
    monkeypatch.setattr(module, "_lancedb_service", svc)
    yield svc
    svc.close()


@pytest.fixture
def db_session(tmp_db):
    """Yield a DB session from the test database, closes after use."""
    engine, SessionLocal = tmp_db
    session = SessionLocal()
    yield session
    session.close()


class QueryCounter:
    """SQL statements executed on an engine while active (``executemany`` counts once)."""

    def __init__(self, engine):
        self._engine = engine
        self.statements: list[str] = []

    def _record(self, conn, cursor, statement, parameters, context, executemany):
        self.statements.append(statement)

    def __enter__(self):
        from sqlalchemy import event

        self.statements = []
        event.listen(self._engine, "before_cursor_execute", self._record)
        return self

    def __exit__(self, *exc):
        from sqlalchemy import event

        event.remove(self._engine, "before_cursor_execute", self._record)

    @property
    def count(self) -> int:
        return len(self.statements)

    def selects(self, table: str | None = None) -> list[str]:
        """SELECT statements, optionally only those reading ``FROM <table>``."""
        found = [s for s in self.statements if s.lstrip().upper().startswith("SELECT")]
        if table is not None:
            found = [s for s in found if f"FROM {table}" in s]
        return found


@pytest.fixture
def query_counter(tmp_db):
    """Count SQL statements on the test engine: ``with query_counter as q: ...; q.count``.

    Use it to pin query counts so N+1 patterns can't creep back in.
    """
    engine, _ = tmp_db
    return QueryCounter(engine)


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
        with TestClient(app, base_url="http://127.0.0.1:8000") as client:
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
