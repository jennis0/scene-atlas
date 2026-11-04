"""Unit tests for maintenance helper functions.

Tests sweep_orphaned_store_files(). backup_sqlite is covered by
test_backup_restore.py (integration test).
"""

import os
import time
from pathlib import Path

import pytest

from backend.app.models import Image
from backend.app.services.image_store import ImageStore
from backend.pipeline.maintenance import sweep_orphaned_store_files

# ---------------------------------------------------------------------------
# sweep_orphaned_store_files
# ---------------------------------------------------------------------------


@pytest.fixture
def stores(tmp_db, tmp_path, monkeypatch):
    from backend.app import services

    engine, SessionLocal = tmp_db
    monkeypatch.setattr("backend.app.config.settings.database_url", str(engine.url))
    images = ImageStore(tmp_path / "library")
    thumbs = ImageStore(tmp_path / "thumbs")
    monkeypatch.setattr(services, "_image_store", images)
    monkeypatch.setattr(services, "_thumbnail_store", thumbs)
    return SessionLocal, images, thumbs


def _age(path: Path, seconds: float = 7200) -> Path:
    old = time.time() - seconds
    os.utime(path, (old, old))
    return path


def _put(store: ImageStore, key: str, age: float = 7200) -> Path:
    path = store.get_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    return _age(path, age)


def _add_image(SessionLocal, storage_key: str, thumbnail_key: str) -> None:
    with SessionLocal() as db:
        db.add(
            Image(filename="f.jpg", storage_key=storage_key, thumbnail_key=thumbnail_key, name="n")
        )
        db.commit()


class TestSweepOrphanedStoreFiles:
    def test_known_files_are_kept_and_orphans_deleted(self, stores):
        SessionLocal, images, thumbs = stores
        for n in range(10):
            stem = f"{n:02d}aa{n:028x}"
            _add_image(SessionLocal, f"{stem}.jpg", f"{stem}_400x400.jpg")
            _put(images, f"{stem}.jpg")
            for size in (150, 400, 800):
                _put(thumbs, f"{stem}_{size}x{size}.jpg")
        orphan = _put(images, "ffee0000000000000000000000000000.png")
        orphan_thumb = _put(thumbs, "ffee0000000000000000000000000000_150x150.jpg")

        result = sweep_orphaned_store_files()

        assert result == {
            "orphaned_images": 1,
            "deleted_images": 1,
            "orphaned_thumbnails": 1,
            "deleted_thumbnails": 1,
        }
        assert not orphan.exists() and not orphan_thumb.exists()
        assert len(list(images.base_dir.rglob("*.jpg"))) == 10
        assert len(list(thumbs.base_dir.rglob("*.jpg"))) == 30

    def test_legacy_short_keys_are_recognised(self, stores):
        SessionLocal, images, thumbs = stores
        _add_image(SessionLocal, "a1b2c3d4e5f6.jpg", "a1b2c3d4e5f6_400x400.webp")
        kept = _put(images, "a1b2c3d4e5f6.jpg")
        kept_thumb = _put(thumbs, "a1b2c3d4e5f6_800x800.webp")
        sweep_orphaned_store_files()
        assert kept.exists() and kept_thumb.exists()

    def test_backups_and_incoming_are_never_touched(self, stores):
        _, images, _ = stores
        backup = images.base_dir / "backups" / "2026-01-01" / "battlemap.db"
        incoming = images.base_dir / ".incoming" / "abcd.jpg"
        for path in (backup, incoming):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x")
            _age(path)
        sweep_orphaned_store_files()
        assert backup.exists() and incoming.exists()

    def test_recent_files_are_left_alone(self, stores):
        _, images, _ = stores
        fresh = _put(images, "abcd0000000000000000000000000000.jpg", age=10)
        result = sweep_orphaned_store_files()
        assert fresh.exists()
        assert result["orphaned_images"] == 0

    def test_refuses_when_most_of_the_store_looks_orphaned(self, stores):
        """E.g. the wrong database is in use: deleting would destroy the library."""
        _, images, _ = stores
        files = [_put(images, f"{n:02x}cd{n:028x}.jpg") for n in range(40)]
        result = sweep_orphaned_store_files()
        assert result["orphaned_images"] == 40
        assert result["deleted_images"] == 0
        assert all(p.exists() for p in files)
