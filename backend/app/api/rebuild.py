"""Rebuild the library from a metadata export (design/export-backup-move.md §8).

Upload the export, check it (a job: a large file takes minutes to read), build the new
library alongside the live one (a job), then apply: the backend restarts into it. Cancel
discards the upload and any build. Nothing changes the live library until the restart.

The POSTs take a JSON body (``{}``), so a page on another site can't send them: a
cross-origin JSON POST needs a CORS preflight, which only configured origins pass.
"""

import atexit
import logging
import os
import signal
import threading
from contextlib import contextmanager

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ...pipeline import export_library
from ...pipeline import library_rebuild as lr
from ...pipeline.library_move import JOB_NAME as MOVE_JOB
from ...pipeline.metadata_export import export_lock
from ..config import settings
from ..models import ImportItem
from ..models.schemas import RebuildApplied, RebuildStatus
from ..services.app_settings import get_settings as get_app_settings
from ..services.job_runner import PURGE_JOB_NAME, get_job_runner
from .dependencies import acquire_heavy_op, get_db
from .imports import stream_body
from .rate_limits import limiter

logger = logging.getLogger(__name__)
router = APIRouter()

CHECK_JOB = "Checking the export"
_JOBS = (CHECK_JOB, lr.JOB_NAME)
# A server stopping for a rebuild exits with this, so a supervisor restarting only on
# failure (systemd's Restart=on-failure) restarts it too
RESTART_EXIT_CODE = 75
_Confirm = Body(...)  # each POST must have a JSON body ({}): see the module docstring


@contextmanager
def _exclusive():
    """No other rebuild step, purge, export or set-aside starts until the caller's job is
    submitted (purge and the full export take the same lock)."""
    with export_lock:
        runner = get_job_runner()
        for job in (*_JOBS, PURGE_JOB_NAME, export_library.JOB_NAME, lr.SET_ASIDE_JOB, MOVE_JOB):
            if runner.has_active_job(job):
                raise HTTPException(status_code=409, detail=f"{job} is running; try again after")
        reason = lr.busy()
        if reason:
            raise HTTPException(status_code=409, detail=reason)
        yield runner


@router.get("", response_model=RebuildStatus)
def rebuild_status():
    """Where a rebuild has got to, so Settings can pick it up when reopened."""
    runner = get_job_runner()
    check = lr.saved_check()
    return RebuildStatus(
        staged=lr.staged_path().is_file(),
        check=check.__dict__ if check else None,
        check_error=lr.check_error(),
        built=lr.is_built() and not runner.has_active_job(lr.JOB_NAME),
        job_id=next((j for j in (runner.get_active_job_id(name) for name in _JOBS) if j), None),
        summary=lr.last_summary(),
        set_aside_running=runner.has_active_job(lr.SET_ASIDE_JOB) or lr.set_aside_pending(),
    )


@router.put("/upload", response_model=RebuildStatus)
async def upload_export(request: Request, db=Depends(get_db), _admission=Depends(acquire_heavy_op)):
    """The metadata export (raw body), replacing any staged before."""
    with _exclusive():
        pass
    limit = get_app_settings(db).max_import_file_size
    staged = lr.staged_path()
    part = staged.with_name(staged.name + ".part")
    await stream_body(request, part, limit)
    lr.discard()
    os.replace(part, staged)
    return rebuild_status()


@router.post("/check", status_code=202)
@limiter.limit(lambda: settings.rate_limit_expensive)
def start_check(request: Request, _body: dict = _Confirm):
    with _exclusive() as runner:
        if not lr.staged_path().is_file():
            raise HTTPException(status_code=409, detail="Upload an export first")
        return {"job_id": runner.submit(lr.check_job, name=CHECK_JOB)}


@router.post("/build", status_code=202)
@limiter.limit(lambda: settings.rate_limit_expensive)
def start_build(request: Request, _body: dict = _Confirm):
    with _exclusive() as runner:
        if lr.saved_check() is None:
            raise HTTPException(status_code=409, detail="Check the export first")
        return {"job_id": runner.submit(lr.build_job, name=lr.JOB_NAME)}


def _refuse_if_changed(db: Session) -> None:
    checked = lr.saved_check()
    if checked is None or checked.library != lr.fingerprint(db):
        raise HTTPException(
            status_code=409,
            detail="The library has changed since the export was checked. Check it again to "
            "see what a rebuild would change now.",
        )
    importing = (
        db.query(ImportItem.id)
        .filter(ImportItem.state.in_(("awaiting_bytes", "ready", "processing")))
        .first()
    )
    if importing:
        raise HTTPException(
            status_code=409, detail="An import is in progress; let it finish, then check again"
        )


@router.post("/apply", response_model=RebuildApplied)
@limiter.limit(lambda: settings.rate_limit_destructive)
def apply_rebuild(request: Request, _body: dict = _Confirm, db: Session = Depends(get_db)):
    """Swap the built library in at a restart. The desktop app restarts the backend
    itself; a server stops, and its service manager (Compose's ``restart:``) starts it
    again."""
    with _exclusive():
        _refuse_if_changed(db)
        try:
            lr.request_swap()
        except lr.RebuildError as e:
            raise HTTPException(status_code=409, detail=str(e)) from None
    if settings.app_mode == "app":
        return RebuildApplied(restart="app")
    logger.warning("Stopping to put the rebuilt library in place; the service should restart")
    # A graceful shutdown (as for docker stop) after this response is sent, then a
    # non-zero exit for supervisors that restart only on failure
    atexit.register(os._exit, RESTART_EXIT_CODE)
    threading.Timer(1.0, os.kill, (os.getpid(), signal.SIGTERM)).start()
    return RebuildApplied(restart="server")


@router.delete("")
def cancel_rebuild():
    """Forget the export, its check and its build, and the last rebuild's summary."""
    with _exclusive():
        lr.discard()
    (lr.rebuild_dir() / "summary.json").unlink(missing_ok=True)
    return {"ok": True}
