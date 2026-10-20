"""Unit tests for maintenance helper functions.

Tests rotate_backups() as a pure function and sweep_orphaned_store_files().
The backup_sqlite and full backup_database functions are already covered by
test_backup_restore.py (integration test).
"""

import os
import time
from pathlib import Path

import pytest

from backend.app.models import Image
from backend.app.services.image_store import ImageStore
from backend.pipeline.maintenance import rotate_backups, sweep_orphaned_store_files

# ---------------------------------------------------------------------------
# rotate_backups
# ---------------------------------------------------------------------------


def _make_backup_dir(root: Path, name: str) -> Path:
    """Create an empty backup directory with the given name."""
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    return d


class TestRotateBackups:
    def test_empty_root_returns_zero(self, tmp_path):
        root = tmp_path / "backups"
        root.mkdir()
        result = rotate_backups(root)
        assert result == 0

    def test_nonexistent_root_returns_zero(self, tmp_path):
        result = rotate_backups(tmp_path / "no_such_dir")
        assert result == 0

    def test_keeps_most_recent_n_backups(self, tmp_path):
        root = tmp_path / "backups"
        root.mkdir()
        # Create 5 backups in chronological order
        names = [
            "20240101_000000",
            "20240102_000000",
            "20240103_000000",
            "20240104_000000",
            "20240105_000000",
        ]
        for name in names:
            _make_backup_dir(root, name)

        deleted = rotate_backups(root, keep_daily=3, keep_weekly=0)

        # 5 created, 3 kept → 2 deleted
        assert deleted == 2
        remaining = {d.name for d in root.iterdir() if d.is_dir()}
        # Most recent 3 should survive
        assert "20240103_000000" in remaining
        assert "20240104_000000" in remaining
        assert "20240105_000000" in remaining

    def test_invalid_dirname_format_is_left_alone(self, tmp_path):
        """Directories that don't match YYYYMMDD_HHMMSS format are skipped."""
        root = tmp_path / "backups"
        root.mkdir()
        # Enough valid dirs to trigger rotation
        for day in range(1, 11):
            _make_backup_dir(root, f"202401{day:02d}_120000")
        # Add one with an invalid name
        invalid = _make_backup_dir(root, "unknown_backup_dir")

        rotate_backups(root, keep_daily=3, keep_weekly=1)

        # Invalid-name dir must still be there
        assert invalid.exists()

    def test_other_dirs_take_no_daily_slot(self, tmp_path):
        """pre-migration/ (and any non-timestamp name) sorts after the dates in reverse
        order; it must neither be deleted nor push a real backup out of a daily slot."""
        root = tmp_path / "backups"
        root.mkdir()
        for day in range(1, 6):
            _make_backup_dir(root, f"202401{day:02d}_000000")
        others = [_make_backup_dir(root, n) for n in ("pre-migration", "zz", "2024_notes")]
        (root / "readme.txt").write_text("left alone")

        deleted = rotate_backups(root, keep_daily=3, keep_weekly=0)

        assert deleted == 2
        remaining = {d.name for d in root.iterdir()}
        assert remaining == {
            "20240103_000000",
            "20240104_000000",
            "20240105_000000",
            "pre-migration",
            "zz",
            "2024_notes",
            "readme.txt",
        }
        assert all(d.exists() for d in others)

    def test_weekly_retention_keeps_one_per_week(self, tmp_path):
        root = tmp_path / "backups"
        root.mkdir()
        # 14 daily backups — 2 weeks worth (2024-01-01 .. 2024-01-14)
        for day in range(1, 15):
            _make_backup_dir(root, f"202401{day:02d}_000000")

        deleted = rotate_backups(root, keep_daily=3, keep_weekly=2)

        # Daily: 14, 13, 12. Weekly: 11, then 4 (the first a full week older).
        remaining = {d.name for d in root.iterdir()}
        assert remaining == {f"202401{day:02d}_000000" for day in (14, 13, 12, 11, 4)}
        assert deleted == 9

    def test_all_fit_in_keep_daily_nothing_deleted(self, tmp_path):
        root = tmp_path / "backups"
        root.mkdir()
        _make_backup_dir(root, "20240101_000000")
        _make_backup_dir(root, "20240102_000000")

        deleted = rotate_backups(root, keep_daily=7, keep_weekly=4)
        assert deleted == 0


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
