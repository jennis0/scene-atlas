"""Periodic ingest maintenance (ADR-018, design/ingestion.md §9).

Everything here is driven by item and job state, never by file timestamps alone,
and nothing here deletes images. Active imports are never expired.
"""

from __future__ import annotations

import logging
import shutil
import time
from datetime import timedelta

from backend.app.config import settings
from backend.app.models import ImportGroup, ImportItem, ImportJob
from backend.app.services import ingest_state as st
from backend.app.services.shutdown import raise_if_shutting_down

from .ingest_queue import KIND_SORTED_OUT, remove_staged, skip_items, utcnow, write_session

logger = logging.getLogger(__name__)

# Unfinished uploads are given up on after this long without any bytes arriving.
ABANDON_AFTER = timedelta(days=7)
# Staged bytes of failed/duplicate items are kept this long after a job finishes,
# so "Retry" and "Import as new copy" work without a re-upload.
KEEP_RETRY_BYTES_FOR = timedelta(days=7)
# Dismissed jobs' rows (not their images) are deleted after this long.
PRUNE_DISMISSED_AFTER = timedelta(days=30)
# Unreferenced files in staging younger than this may be an upload in progress.
STRAY_FILE_GRACE_SECONDS = 3600

_TERMINAL_JOBS = (st.JOB_COMPLETED, st.JOB_CANCELLED)


def abandon_stale_uploads(now=None) -> int:
    """Skip files that were never uploaded for jobs idle for ``ABANDON_AFTER``."""
    now = now or utcnow()
    cutoff = now - ABANDON_AFTER
    skipped = 0
    with write_session() as db:
        jobs = (
            db.query(ImportJob)
            .filter(
                ImportJob.status.in_([st.JOB_ACTIVE, st.JOB_PAUSED]),
                ImportJob.planned_at.isnot(None),
                (ImportJob.last_upload_at.is_(None) & (ImportJob.planned_at < cutoff))
                | (ImportJob.last_upload_at < cutoff),
            )
            .all()
        )
        for job in jobs:
            skipped += skip_items(db, job.id, "Not uploaded", states={st.AWAITING_BYTES})
    if skipped:
        logger.info("Abandoned %d never-uploaded file(s) from stale imports", skipped)
    return skipped


def release_staged_bytes(now=None) -> int:
    """Delete staged files that are no longer needed, based on item state.

    - ``done``/``skipped`` items: always (normally removed immediately; this
      catches a crash between commit and cleanup).
    - ``failed``/``duplicate`` items: once their job is dismissed, or finished
      more than ``KEEP_RETRY_BYTES_FOR`` ago.
    - Items Auto sorted out: never. They can be included from the group editor until
      their job's rows are pruned (design §5.6), which deletes the job's staging folder.
    """
    now = now or utcnow()
    cutoff = now - KEEP_RETRY_BYTES_FOR
    released = 0
    with write_session() as db:
        finished = db.query(ImportItem).filter(
            ImportItem.staging_key.isnot(None),
            ImportItem.state.in_([st.DONE, st.SKIPPED]),
            ImportItem.error_kind.is_(None) | (ImportItem.error_kind != KIND_SORTED_OUT),
        )
        retained = (
            db.query(ImportItem)
            .join(ImportJob, ImportJob.id == ImportItem.job_id)
            .filter(
                ImportItem.staging_key.isnot(None),
                ImportItem.state.in_([st.FAILED, st.DUPLICATE]),
                ImportJob.dismissed_at.isnot(None)
                | (ImportJob.status.in_(_TERMINAL_JOBS) & (ImportJob.completed_at < cutoff)),
            )
        )
        for item in [*finished, *retained]:
            remove_staged(item.job_id, item.staging_key)
            item.staging_key = None
            released += 1
    if released:
        logger.info("Released %d staged file(s)", released)
    return released


def prune_dismissed_jobs(now=None) -> int:
    """Delete job/group/item rows of long-dismissed jobs. Images are untouched."""
    now = now or utcnow()
    with write_session() as db:
        job_ids = [
            job_id
            for (job_id,) in db.query(ImportJob.id).filter(
                ImportJob.dismissed_at.isnot(None),
                ImportJob.dismissed_at < now - PRUNE_DISMISSED_AFTER,
                ImportJob.status.in_(_TERMINAL_JOBS),
            )
        ]
        for job_id in job_ids:
            db.query(ImportItem).filter(ImportItem.job_id == job_id).delete()
            db.query(ImportGroup).filter(ImportGroup.job_id == job_id).delete()
            db.query(ImportJob).filter(ImportJob.id == job_id).delete()
            shutil.rmtree(settings.staging_dir / job_id, ignore_errors=True)
    if job_ids:
        logger.info("Pruned %d dismissed import(s)", len(job_ids))
    return len(job_ids)


def sweep_stray_staging_files() -> int:
    """Delete staging files and directories no item refers to.

    Covers uploads interrupted mid-stream (``.part`` files), jobs deleted
    while their staging remained, and files orphaned by a failed commit. Files
    younger than an hour are left alone: they may be an upload in progress.
    """
    root = settings.staging_dir
    if not root.exists():
        return 0
    with write_session() as db:
        job_ids = {job_id for (job_id,) in db.query(ImportJob.id)}
        referenced = {
            (job_id, key)
            for job_id, staging_key, preview_key in db.query(
                ImportItem.job_id, ImportItem.staging_key, ImportItem.preview_key
            ).filter(ImportItem.staging_key.isnot(None) | ImportItem.preview_key.isnot(None))
            for key in (staging_key, preview_key)
            if key
        }
    removed = 0
    cutoff = time.time() - STRAY_FILE_GRACE_SECONDS
    for job_dir in root.iterdir():
        if not job_dir.is_dir():
            continue
        if job_dir.name not in job_ids:
            if job_dir.stat().st_mtime < cutoff:
                shutil.rmtree(job_dir, ignore_errors=True)
                removed += 1
            continue
        for path in job_dir.iterdir():
            if (
                path.is_file()
                and (job_dir.name, path.name) not in referenced
                and path.stat().st_mtime < cutoff
            ):
                path.unlink(missing_ok=True)
                removed += 1
    if removed:
        logger.info("Removed %d stray staging file(s)/folder(s)", removed)
    return removed


def run_ingest_maintenance() -> dict[str, int]:
    """Scheduled entry point (every 6 h, and on startup when overdue)."""
    from .ingest_worker import get_ingest_worker

    steps = {
        "abandoned": abandon_stale_uploads,
        "released": release_staged_bytes,
        "pruned": prune_dismissed_jobs,
        "stray": sweep_stray_staging_files,
    }
    result = {}
    for key, step in steps.items():
        raise_if_shutting_down()
        result[key] = step()
    get_ingest_worker().bump()
    return result
