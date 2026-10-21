"""The app locks both storage roots for its lifetime and refuses to start without them."""

import pytest
from fastapi.testclient import TestClient

from backend.app.config import settings
from backend.app.main import app
from backend.app.storage_lock import StorageLockedError
from backend.tests.unit.test_storage_lock import _hold_in_child, child_can_lock


@pytest.fixture(autouse=True)
def _no_ingest_worker(monkeypatch):
    monkeypatch.setattr(settings, "ingest_worker_enabled", False)
    settings.images_dir.mkdir(parents=True, exist_ok=True)


def _roots():
    return [settings.data_dir, settings.images_dir]


def test_lifespan_holds_locks_until_shutdown():
    with TestClient(app):
        for root in _roots():
            assert not child_can_lock(root)
    for root in _roots():
        assert child_can_lock(root)


@pytest.mark.parametrize("root_index", [0, 1])
def test_startup_fails_when_another_backend_holds_a_root(root_index):
    holder = _hold_in_child(_roots()[root_index])
    try:
        with pytest.raises(StorageLockedError), TestClient(app):
            pass
    finally:
        holder.kill()
        holder.wait()
    # A partial acquisition is rolled back.
    for root in _roots():
        assert child_can_lock(root)
