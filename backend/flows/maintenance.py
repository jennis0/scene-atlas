"""Maintenance tasks: database backup and staging cleanup.

Functions:
    backup_database  — Snapshot SQLite + Qdrant, rotate old backups. Runs daily.
    cleanup_staging  — Remove stale staging directories older than 24h. Runs every 6h.

Scheduled by the Scheduler (started in FastAPI lifespan).  Also runnable
from the CLI: ``uv run python -m backend.flows.maintenance``
"""

import shutil
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from backend.app.config import settings
from backend.flows.logger import get_logger


# ---------------------------------------------------------------------------
# Backup tasks
# ---------------------------------------------------------------------------


def backup_sqlite(backup_dir: Path, db_path: Path | None = None) -> Path:
    """Create a consistent SQLite snapshot using the sqlite3.backup() API.

    Uses the built-in sqlite3 backup API rather than file copy so the snapshot
    is guaranteed consistent even if the database is being written to at the
    same time.

    Args:
        backup_dir: Directory where the backup will be written.
        db_path: Path to the source SQLite file. Defaults to the application
            database derived from ``settings.database_url``.
    """
    logger = get_logger(__name__)
    if db_path is None:
        db_path = settings.db_path
    backup_path = backup_dir / db_path.name
    backup_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(str(db_path)) as src, sqlite3.connect(str(backup_path)) as dst:
        src.backup(dst)

    size_kb = backup_path.stat().st_size // 1024
    logger.info(f"SQLite backed up to {backup_path} ({size_kb} KB)")
    return backup_path


def backup_qdrant(backup_dir: Path) -> Path | None:
    """Copy the embedded Qdrant storage directory for backup.

    Returns the backup path on success, or None if Qdrant is not initialised.
    Non-fatal: the overall backup still succeeds if only SQLite was backed up.
    """
    logger = get_logger(__name__)
    try:
        from backend.app.services.qdrant_service import get_qdrant_service

        svc = get_qdrant_service()
        backup_path = svc.backup_storage(backup_dir)
        return backup_path
    except Exception as e:
        logger.warning(f"Qdrant backup failed: {e}")
        return None


def rotate_backups(backups_root: Path, keep_daily: int = 7, keep_weekly: int = 4) -> int:
    """Rotate backup directories: keep the most recent N daily plus M weekly.

    Backup directories are named ``YYYYMMDD_HHMMSS`` so lexicographic sort
    is chronological.

    Strategy:
    - Keep the last ``keep_daily`` backups unconditionally (daily retention).
    - From older backups, keep one per 7-day window up to ``keep_weekly`` total.
    - Delete everything else.

    Returns the number of directories deleted.
    """
    logger = get_logger(__name__)
    if not backups_root.exists():
        return 0

    dirs = sorted(
        [d for d in backups_root.iterdir() if d.is_dir()],
        reverse=True,  # most recent first
    )

    to_keep: set[Path] = set()

    # Always keep the most recent N
    for d in dirs[:keep_daily]:
        to_keep.add(d)

    # From the remainder, keep one per week up to keep_weekly
    last_kept_ts: datetime | None = None
    weekly_count = 0
    for d in dirs[keep_daily:]:
        if weekly_count >= keep_weekly:
            break
        try:
            ts = datetime.strptime(d.name, "%Y%m%d_%H%M%S")
        except ValueError:
            continue  # unknown format — leave it alone
        if last_kept_ts is None or (last_kept_ts - ts) >= timedelta(days=7):
            to_keep.add(d)
            last_kept_ts = ts
            weekly_count += 1

    deleted = 0
    for d in dirs:
        if d not in to_keep:
            shutil.rmtree(d, ignore_errors=True)
            logger.info(f"Rotated old backup: {d.name}")
            deleted += 1

    return deleted


def backup_database() -> dict:
    """Full backup: SQLite snapshot + Qdrant snapshot + rotation."""
    logger = get_logger(__name__)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    backups_root = settings.data_dir / "backups"
    backup_dir = backups_root / timestamp

    db_backup = backup_sqlite(backup_dir)
    qdrant_backup = backup_qdrant(backup_dir)
    deleted = rotate_backups(backups_root)

    result = {
        "timestamp": timestamp,
        "db_backup": str(db_backup),
        "qdrant_backup": str(qdrant_backup) if qdrant_backup else None,
        "rotated": deleted,
    }
    logger.info(f"Backup complete: {result}")
    return result


# ---------------------------------------------------------------------------
# Staging cleanup tasks
# ---------------------------------------------------------------------------


def cleanup_stale_staging(max_age_hours: int = 24) -> int:
    """Remove staging job directories older than ``max_age_hours``.

    Uses directory mtime as the age proxy. Catches the case where a background
    job died mid-import and left behind a staging directory that will never
    be cleaned up by the import flow itself.

    Returns the number of directories removed.
    """
    logger = get_logger(__name__)
    staging_root = settings.staging_dir
    if not staging_root.exists():
        return 0

    cutoff = datetime.now(UTC) - timedelta(hours=max_age_hours)
    deleted = 0

    for staging_dir in staging_root.iterdir():
        if not staging_dir.is_dir():
            continue
        mtime = datetime.fromtimestamp(staging_dir.stat().st_mtime, tz=UTC)
        if mtime < cutoff:
            age = datetime.now(UTC) - mtime
            shutil.rmtree(staging_dir, ignore_errors=True)
            logger.info(f"Cleaned stale staging dir: {staging_dir.name} (age: {age})")
            deleted += 1

    return deleted


def cleanup_staging() -> dict:
    """Remove staging directories abandoned by crashed or cancelled imports.

    Scheduled every 6 hours. Complements the immediate cleanup done at the end
    of process_import_job — this catches any leftovers from crashes or the
    single-group import path.
    """
    logger = get_logger(__name__)
    deleted = cleanup_stale_staging()
    logger.info(f"Staging cleanup complete: removed {deleted} stale director(ies)")
    return {"deleted": deleted}
