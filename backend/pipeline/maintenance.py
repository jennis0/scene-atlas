"""Maintenance tasks: database backup, staging cleanup, and stale job expiry.

Functions:
    backup_database     — Snapshot SQLite + Qdrant, rotate old backups. Runs daily.
    cleanup_staging     — Remove stale staging directories older than 24h. Runs every 6h.
    expire_stale_jobs   — Mark abandoned import jobs as expired. Runs every 6h.

Scheduled by the Scheduler (started in FastAPI lifespan).  Also runnable
from the CLI: ``uv run python -m backend.pipeline.maintenance``
"""

import logging
import shutil
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from backend.app.config import settings

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
    logger = logging.getLogger(__name__)
    if db_path is None:
        db_path = settings.db_path
    backup_path = backup_dir / db_path.name
    backup_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(str(db_path)) as src, sqlite3.connect(str(backup_path)) as dst:
        src.backup(dst)

    size_kb = backup_path.stat().st_size // 1024
    logger.info("SQLite backed up to %s (%s KB)", backup_path, size_kb)
    return backup_path


def backup_qdrant(backup_dir: Path) -> Path | None:
    """Copy the embedded Qdrant storage directory for backup.

    Returns the backup path on success, or None if Qdrant is not initialised.
    Non-fatal: the overall backup still succeeds if only SQLite was backed up.
    """
    logger = logging.getLogger(__name__)
    try:
        from backend.app.services.qdrant_service import get_qdrant_service

        svc = get_qdrant_service()
        backup_path = svc.backup_storage(backup_dir)
        return backup_path
    except Exception as e:
        logger.warning("Qdrant backup failed: %s", e)
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
    logger = logging.getLogger(__name__)
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
            logger.info("Rotated old backup: %s", d.name)
            deleted += 1

    return deleted


def backup_database() -> dict:
    """Full backup: SQLite snapshot + Qdrant snapshot + rotation."""
    logger = logging.getLogger(__name__)
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
    logger.info("Backup complete: %s", result)
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
    logger = logging.getLogger(__name__)
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
            logger.info("Cleaned stale staging dir: %s (age: %s)", staging_dir.name, age)
            deleted += 1

    return deleted


def cleanup_staging() -> dict:
    """Remove staging directories abandoned by crashed or cancelled imports.

    Scheduled every 6 hours.  Catches orphaned staging dirs that were not
    cleaned up by /finalize, /cancel, or expire_stale_jobs.
    """
    logger = logging.getLogger(__name__)
    deleted = cleanup_stale_staging()
    logger.info("Staging cleanup complete: removed %s stale director(ies)", deleted)
    return {"deleted": deleted}


# ---------------------------------------------------------------------------
# Stale import job expiry
# ---------------------------------------------------------------------------


def expire_stale_jobs(max_age_hours: int = 48) -> dict:
    """Mark staging/active import jobs as expired if no activity for ``max_age_hours``.

    Cleans up their staging directories.  Skips jobs that still have running
    groups (to avoid killing in-progress work).

    Scheduled every 6 hours.  Solves the problem of abandoned import sessions
    that would otherwise live forever in the database.
    """
    logger = logging.getLogger(__name__)

    from backend.app.models import ImportGroupJob, ImportJob, get_engine, get_session_local

    engine = get_engine(settings.database_url)
    SessionLocal = get_session_local(engine)
    db = SessionLocal()

    try:
        cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=max_age_hours)
        stale_statuses = {"staging", "active", "uploading", "awaiting_input"}

        # Find stale jobs: non-terminal and no recent activity
        stale_jobs = (
            db.query(ImportJob)
            .filter(
                ImportJob.status.in_(stale_statuses),
            )
            .all()
        )

        expired_count = 0
        for job in stale_jobs:
            # Use updated_at if available, else created_at
            last_activity = job.updated_at or job.created_at
            if last_activity is None or last_activity >= cutoff:
                continue

            # Don't expire jobs with running groups
            running = (
                db.query(ImportGroupJob)
                .filter(ImportGroupJob.job_id == job.id, ImportGroupJob.status == "running")
                .count()
            )
            if running > 0:
                logger.info(
                    "Skipping expiry for job %s: %s group(s) still running", job.id, running
                )
                continue

            job.status = "expired"
            job.completed_at = datetime.now(UTC).replace(tzinfo=None)

            # Clean up staging directory
            staging_dir = settings.staging_dir / job.id
            if staging_dir.exists():
                shutil.rmtree(staging_dir, ignore_errors=True)
                logger.info("Cleaned staging for expired job %s", job.id)

            expired_count += 1
            logger.info("Expired stale import job %s (last activity: %s)", job.id, last_activity)

        db.commit()
    finally:
        db.close()

    logger.info("Stale job expiry complete: expired %s job(s)", expired_count)
    return {"expired": expired_count}


# ---------------------------------------------------------------------------
# Startup: mark interrupted jobs
# ---------------------------------------------------------------------------


def mark_interrupted_jobs(db=None) -> int:
    """Mark import jobs that were interrupted by a server restart as broken.

    Jobs in 'uploading' or 'active' states cannot be resumed after a restart
    because their background processing threads are gone.  This is called at
    server startup to transition them to 'broken' so users can see the problem
    and cancel/clean up from the ActivityDock.

    Args:
        db: Optional SQLAlchemy session.  If None, a new session is created and
            committed/closed by this function.  Pass a session in unit tests.

    Returns:
        Number of jobs marked as broken.
    """
    logger = logging.getLogger(__name__)
    from backend.app.models import ImportGroupJob, ImportJob, get_engine, get_session_local

    own_session = db is None
    if own_session:
        engine = get_engine(settings.database_url)
        SessionLocal = get_session_local(engine)
        db = SessionLocal()

    try:
        interrupted_statuses = ("uploading", "active")
        jobs = (
            db.query(ImportJob)
            .filter(ImportJob.status.in_(interrupted_statuses))
            .all()
        )
        if not jobs:
            return 0

        now = datetime.now(UTC).replace(tzinfo=None)
        count = 0
        for job in jobs:
            logger.warning(
                "Marking import job %s as broken (was '%s' at server restart)",
                job.id,
                job.status,
            )
            # Mark running child groups as failed
            affected = db.query(ImportGroupJob).filter(
                ImportGroupJob.job_id == job.id,
                ImportGroupJob.status == "running",
            ).update(
                {"status": "failed", "completed_at": now},
                synchronize_session=False,
            )
            if affected:
                logger.warning(
                    "  Marked %d running group job(s) as failed for job %s", affected, job.id
                )
            job.status = "broken"
            job.error_message = "Server was restarted before this import could complete"
            job.completed_at = now
            job.updated_at = now
            count += 1

        if own_session:
            db.commit()
        return count

    except Exception:
        if own_session:
            db.rollback()
        logger.exception("Error marking interrupted import jobs")
        return 0
    finally:
        if own_session:
            db.close()
