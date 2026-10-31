"""Integration test: backup -> corrupt -> restore -> verify data integrity.

Tests that the backup_sqlite function produces a consistent, restorable
snapshot. Does NOT require a running LanceDB instance (vector DB snapshot creation
is skipped; that path is covered by the e2e suite which requires live infrastructure).

Run with:
    uv run --extra dev pytest backend/tests/integration/test_backup_restore.py -v
"""

import sqlite3
from pathlib import Path

from backend.app.models import Color, Image, ImageGroup, Tag
from backend.app.models.database import get_engine, get_session_local, seed_tag_categories
from backend.pipeline.maintenance import backup_sqlite

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_test_data(engine) -> dict:
    """Insert a known set of records and return expected counts."""
    SessionLocal = get_session_local(engine)
    db = SessionLocal()
    try:
        seed_tag_categories(db)

        # Image group
        group = ImageGroup(base_name="Forest Map", author="TestAuthor")
        db.add(group)
        db.flush()

        # Two images in the group
        img1 = Image(
            filename="forest_night.jpg",
            storage_key="abc123_night.jpg",
            name="Forest Map",
            author="TestAuthor",
            width=800,
            height=600,
            file_size=100_000,
            content_hash="a" * 64,
            group_id=group.id,
        )
        img2 = Image(
            filename="forest_day.jpg",
            storage_key="abc123_day.jpg",
            name="Forest Map",
            author="TestAuthor",
            width=800,
            height=600,
            file_size=90_000,
            content_hash="b" * 64,
            group_id=group.id,
        )
        db.add_all([img1, img2])
        db.flush()

        # Tags
        db.add(Tag(image_id=img1.id, category="lighting", value="night", source="auto"))
        db.add(Tag(image_id=img2.id, category="lighting", value="day", source="auto"))

        # Colors
        db.add(Color(image_id=img1.id, color_hex="#1a2b3c", percentage=60.0, color_order=1))
        db.add(Color(image_id=img2.id, color_hex="#d4a853", percentage=50.0, color_order=1))

        db.commit()

        return {
            "image_count": 2,
            "tag_count": 2,
            "color_count": 2,
            "group_count": 1,
            "img1_hash": img1.content_hash,
            "img2_hash": img2.content_hash,
        }
    finally:
        db.close()


def _query_counts(engine) -> dict:
    """Query current record counts from the database."""
    from sqlalchemy import text

    with engine.connect() as conn:
        return {
            "image_count": conn.execute(text("SELECT COUNT(*) FROM images")).scalar(),
            "tag_count": conn.execute(text("SELECT COUNT(*) FROM tags")).scalar(),
            "color_count": conn.execute(text("SELECT COUNT(*) FROM colors")).scalar(),
            "group_count": conn.execute(text("SELECT COUNT(*) FROM variant_groups")).scalar(),
        }


def _query_content_hashes(engine) -> set[str]:
    from sqlalchemy import text

    with engine.connect() as conn:
        rows = conn.execute(text("SELECT content_hash FROM images")).fetchall()
    return {r[0] for r in rows}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_backup_creates_readable_snapshot(tmp_path, tmp_db):
    """backup_sqlite() produces a valid SQLite file with correct data."""
    engine, _ = tmp_db
    expected = _seed_test_data(engine)

    # Not str(engine.url): SQLAlchemy 2.1 percent-encodes a Windows path in it.
    db_path = Path(engine.url.database)
    backup_dir = tmp_path / "backups" / "20260101_030000"
    backup_path = backup_sqlite(backup_dir, db_path=db_path)

    assert backup_path.exists(), "Backup file was not created"
    assert backup_path.stat().st_size > 0, "Backup file is empty"

    # Verify backup is a readable SQLite database with the expected data
    with sqlite3.connect(str(backup_path)) as conn:
        img_count = conn.execute("SELECT COUNT(*) FROM images").fetchone()[0]
        tag_count = conn.execute("SELECT COUNT(*) FROM tags").fetchone()[0]

    assert img_count == expected["image_count"]
    assert tag_count == expected["tag_count"]


def test_restore_from_backup_preserves_all_data(tmp_path, tmp_db):
    """Full backup → corrupt → restore cycle preserves all records exactly."""
    engine, _ = tmp_db
    expected = _seed_test_data(engine)

    # Get path to the test database (not from str(engine.url), which percent-encodes it)
    db_path = Path(engine.url.database)
    db_url = f"sqlite:///{db_path}"

    backup_dir = tmp_path / "backup"
    backup_path = backup_sqlite(backup_dir, db_path=db_path)

    # Simulate corruption by overwriting the original database
    engine.dispose()  # close all connections before overwriting
    db_path.write_bytes(b"CORRUPTED")

    # Restore: copy backup back and re-open
    import shutil

    shutil.copy2(backup_path, db_path)

    # Re-open the restored database
    restored_engine = get_engine(db_url)
    # Stamp at head since this is a pre-Alembic-stamped restored DB
    from pathlib import Path as _Path

    from alembic import command
    from alembic.config import Config as AlembicConfig

    alembic_ini = _Path(__file__).parent.parent.parent.parent / "alembic.ini"
    alembic_cfg = AlembicConfig(str(alembic_ini))
    alembic_cfg.set_main_option("sqlalchemy.url", db_url)
    command.upgrade(alembic_cfg, "head")  # should be a no-op since version is stamped
    # Regression: env.py's fileConfig disabled every existing logger, which silenced
    # the app's logging (and broke caplog in later tests) for the rest of the process.
    import logging

    disabled = [
        name
        for name, logger in logging.Logger.manager.loggerDict.items()
        if name.startswith("backend.") and isinstance(logger, logging.Logger) and logger.disabled
    ]
    assert disabled == []

    counts = _query_counts(restored_engine)
    assert counts["image_count"] == expected["image_count"]
    assert counts["tag_count"] == expected["tag_count"]
    assert counts["color_count"] == expected["color_count"]
    assert counts["group_count"] == expected["group_count"]

    # Verify content hashes — proves actual image data is preserved
    restored_hashes = _query_content_hashes(restored_engine)
    assert expected["img1_hash"] in restored_hashes
    assert expected["img2_hash"] in restored_hashes

    restored_engine.dispose()
