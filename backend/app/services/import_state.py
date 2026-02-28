"""Import job state machine — single authoritative transition function.

Every status change to an ImportJob goes through transition_job_status().
Nothing else should mutate ImportJob.status directly (except initial creation
endpoints like /init and /upload).

State machine:
    uploading → staging → active ↔ awaiting_input → completed/failed
                     ↘ cancelled        ↗              ↗
"""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from ..models.database import ImportGroupJob, ImportJob

TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled", "expired"})
GROUP_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})


def transition_job_status(db: Session, job_id: str) -> str:
    """Re-evaluate and set ImportJob.status based on current group states.

    Called after:
    - A group finishes processing (from _finalize_import_job in pipeline)
    - A group is confirmed (from /confirm, /confirm-all endpoints)
    - User calls /finalize

    The caller is responsible for calling db.commit() after this function.

    Returns the new status string.
    """
    job = db.query(ImportJob).filter(ImportJob.id == job_id).first()
    if not job:
        return "unknown"
    if job.status in TERMINAL_STATUSES:
        return job.status

    groups = db.query(ImportGroupJob).filter(ImportGroupJob.job_id == job_id).all()
    if not groups:
        # No groups submitted yet — stay in current status (staging/uploading)
        return job.status

    has_running = any(g.status == "running" for g in groups)
    all_terminal = all(g.status in GROUP_TERMINAL_STATUSES for g in groups)
    has_failures = any(g.status == "failed" for g in groups)

    if has_running:
        new_status = "active"
    elif all_terminal:
        if job.pending_groups > 0 and not job.all_confirmed:
            new_status = "awaiting_input"
        elif has_failures:
            new_status = "failed"
        else:
            new_status = "completed"
    else:
        # Shouldn't normally happen (queued groups?) — keep current status
        new_status = job.status

    if new_status in TERMINAL_STATUSES:
        job.completed_at = datetime.now(UTC).replace(tzinfo=None)

    job.status = new_status
    job.updated_at = datetime.now(UTC).replace(tzinfo=None)
    return new_status
