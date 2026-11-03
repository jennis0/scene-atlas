"""Rebuild the library from a metadata export (design/export-backup-move.md §8).

Upload the export, check it (a job: a large file takes minutes to read), build the new
library alongside the live one (a job), then apply: the backend restarts into it. Cancel
discards the upload and any build. Nothing changes the live library until the restart.
"""

import logging
import os
import signal
import threading

from fastapi import APIRouter, Depends, HTTPException, Request

from ...pipeline import export_library
from ...pipeline import library_rebuild as lr
from ..config import settings
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


def _refuse_while_busy() -> None:
    runner = get_job_runner()
    for job in (*_JOBS, PURGE_JOB_NAME, export_library.JOB_NAME):
        if runner.has_active_job(job):
            raise HTTPException(status_code=409, detail=f"{job} is running; try again after")


@router.get("", response_model=RebuildStatus)
def rebuild_status():
    """Where a rebuild has got to, so Settings can pick it up when reopened."""
    runner = get_job_runner()
    check = lr.saved_check()
    return RebuildStatus(
        staged=lr.staged_path().is_file(),
        check=check.__dict__ if check else None,
        built=(lr.rebuild_dir() / "new" / lr.DB_NAME).is_file()
        and not runner.has_active_job(lr.JOB_NAME),
        job_id=next((j for j in (runner.get_active_job_id(name) for name in _JOBS) if j), None),
        summary=lr.last_summary(),
        set_aside_running=runner.has_active_job(lr.SET_ASIDE_JOB),
    )


@router.put("/upload", response_model=RebuildStatus)
async def upload_export(request: Request, db=Depends(get_db), _admission=Depends(acquire_heavy_op)):
    """The metadata export (raw body), replacing any staged before."""
    _refuse_while_busy()
    limit = get_app_settings(db).max_import_file_size
    staged = lr.staged_path()
    part = staged.with_name(staged.name + ".part")
    await stream_body(request, part, limit)
    lr.discard()
    os.replace(part, staged)
    return rebuild_status()


@router.post("/check", status_code=202)
@limiter.limit(lambda: settings.rate_limit_expensive)
def start_check(request: Request):
    _refuse_while_busy()
    if not lr.staged_path().is_file():
        raise HTTPException(status_code=409, detail="Upload an export first")
    return {"job_id": get_job_runner().submit(lr.check_job, name=CHECK_JOB)}


@router.post("/build", status_code=202)
@limiter.limit(lambda: settings.rate_limit_expensive)
def start_build(request: Request):
    _refuse_while_busy()
    if lr.saved_check() is None:
        raise HTTPException(status_code=409, detail="Check the export first")
    return {"job_id": get_job_runner().submit(lr.build_job, name=lr.JOB_NAME)}


@router.post("/apply", response_model=RebuildApplied)
@limiter.limit(lambda: settings.rate_limit_destructive)
def apply_rebuild(request: Request):
    """Swap the built library in at a restart. The desktop app restarts the backend
    itself; a server stops, and its service manager (Compose's ``restart:``) starts it
    again."""
    _refuse_while_busy()
    try:
        lr.request_swap()
    except lr.RebuildError as e:
        raise HTTPException(status_code=409, detail=str(e)) from None
    if settings.app_mode == "app":
        return RebuildApplied(restart="app")
    logger.warning("Stopping to put the rebuilt library in place; the service should restart")
    # After this response is sent: a graceful shutdown, as for docker stop
    threading.Timer(1.0, os.kill, (os.getpid(), signal.SIGTERM)).start()
    return RebuildApplied(restart="server")


@router.delete("")
def cancel_rebuild():
    _refuse_while_busy()
    lr.discard()
    (lr.rebuild_dir() / "summary.json").unlink(missing_ok=True)
    return {"ok": True}
