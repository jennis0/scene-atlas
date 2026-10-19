"""init_db() snapshots the database before applying pending migrations.

Migrations are one-way: after an update the snapshot is the only way back to the
previous version with its data. Only a database Alembic is about to migrate gets
one; fresh, at-head and unknown-revision databases don't.
"""

import re
import sqlite3
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from backend.app.config import settings
from backend.app.models import get_engine, init_db
from backend.app.models.database import MigrationBackupError
from backend.pipeline import maintenance

ROOT = Path(__file__).resolve().parents[3]


def _config(url: str) -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "backend" / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    cfg.config_file_name = None  # don't let Alembic reconfigure logging
    return cfg


def _head_and_previous() -> tuple[str, str]:
    script = ScriptDirectory.from_config(_config("sqlite://"))
    head = script.get_current_head()
    assert head is not None
    previous = script.get_revision(head).down_revision
    assert isinstance(previous, str), "head should have a single parent"
    return head, previous


def _revision(db_path: Path) -> str | None:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
    return row[0] if row else None


def _image_names(db_path: Path) -> list[str]:
    with sqlite3.connect(db_path) as conn:
        return [r[0] for r in conn.execute("SELECT name FROM images ORDER BY name")]


@pytest.fixture
def backups(tmp_path, monkeypatch) -> Path:
    root = tmp_path / "backups"
    monkeypatch.setattr(settings, "backups_dir", root)
    return root


@pytest.fixture
def old_db(tmp_path) -> tuple[Path, str]:
    """A database one migration behind head, holding one image."""
    _, previous = _head_and_previous()
    db_path = tmp_path / "battlemap.db"
    url = f"sqlite:///{db_path}"
    command.upgrade(_config(url), previous)
    engine = sa.create_engine(url)
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO images (filename, storage_key, name) VALUES ('a.jpg', 'k', 'Old Map')"
            )
        )
    engine.dispose()
    return db_path, previous


def _snapshots(backups: Path) -> list[Path]:
    root = backups / maintenance.PRE_MIGRATION_DIRNAME
    return sorted(root.iterdir()) if root.exists() else []


def test_pending_migration_snapshots_the_old_database(old_db, backups):
    db_path, previous = old_db
    head, _ = _head_and_previous()

    init_db(get_engine(f"sqlite:///{db_path}"))

    [snapshot_dir] = _snapshots(backups)
    assert re.fullmatch(rf"\d{{8}}_\d{{6}}_{re.escape(previous)}", snapshot_dir.name)
    snapshot = snapshot_dir / "battlemap.db"
    assert _revision(snapshot) == previous
    assert _image_names(snapshot) == ["Old Map"]
    assert _revision(db_path) == head


def test_database_at_head_is_not_snapshotted(tmp_path, backups):
    engine = get_engine(f"sqlite:///{tmp_path / 'battlemap.db'}")
    init_db(engine)  # fresh
    init_db(engine)  # at head

    assert _snapshots(backups) == []


def test_fresh_database_is_not_snapshotted(tmp_path, backups):
    init_db(get_engine(f"sqlite:///{tmp_path / 'battlemap.db'}"))

    assert not backups.exists()


def test_unknown_revision_is_not_snapshotted(tmp_path, backups):
    """A database from a newer build fails to upgrade; snapshotting it on every failed
    start would rotate out the snapshots that lead back."""
    db_path = tmp_path / "battlemap.db"
    engine = get_engine(f"sqlite:///{db_path}")
    init_db(engine)
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE alembic_version SET version_num = 'from_the_future'")

    with pytest.raises(Exception, match="from_the_future"):
        init_db(engine)

    assert _snapshots(backups) == []


def test_keeps_the_five_most_recent_snapshots(old_db, backups):
    db_path, previous = old_db
    root = backups / maintenance.PRE_MIGRATION_DIRNAME
    old = [root / f"2020010{day}_000000_{previous}" for day in range(1, 7)]
    for d in old:
        d.mkdir(parents=True)
    unrelated = root / "notes"
    unrelated.mkdir()

    init_db(get_engine(f"sqlite:///{db_path}"))

    remaining = _snapshots(backups)
    assert unrelated in remaining
    snapshots = [d for d in remaining if d != unrelated]
    assert len(snapshots) == maintenance.PRE_MIGRATION_KEEP
    assert old[-4:] == snapshots[:4]  # the four newest old ones...
    assert snapshots[-1].name.endswith(f"_{previous}")  # ...plus today's
    assert not snapshots[-1].name.startswith("2020")


def test_failed_snapshot_stops_the_migration(old_db, backups, monkeypatch):
    db_path, previous = old_db

    def disk_full(backup_dir, db_path=None):
        backup_dir.mkdir(parents=True)
        (backup_dir / "battlemap.db").write_bytes(b"partial")
        raise OSError("No space left on device")

    monkeypatch.setattr(maintenance, "backup_sqlite", disk_full)

    with pytest.raises(
        MigrationBackupError,
        match="Could not back up the database before migrating it: No space left",
    ):
        init_db(get_engine(f"sqlite:///{db_path}"))

    assert _revision(db_path) == previous
    assert _image_names(db_path) == ["Old Map"]
    assert _snapshots(backups) == []  # nothing partial left to mistake for a snapshot
