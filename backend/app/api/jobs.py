"""Jobs API — query status of background jobs."""

from fastapi import APIRouter, HTTPException

from ..services.job_runner import get_job_runner

router = APIRouter()


@router.get("/")
def list_jobs():
    """List all tracked background jobs (running + recently completed)."""
    runner = get_job_runner()
    return [job.to_dict() for job in runner.list_jobs()]


@router.post("/dismiss-finished")
def dismiss_finished_jobs():
    """Remove every finished job from the activity dock."""
    return {"dismissed": get_job_runner().dismiss_finished()}


@router.post("/{job_id}/dismiss")
def dismiss_job(job_id: str):
    """Remove a finished job from the activity dock."""
    dismissed = get_job_runner().dismiss(job_id)
    if dismissed is None:
        raise HTTPException(status_code=404, detail="Job not found or expired")
    if not dismissed:
        raise HTTPException(status_code=409, detail="Only finished jobs can be dismissed")
    return {"dismissed": 1}


@router.get("/{job_id}")
def get_job(job_id: str):
    """Get status of a specific background job."""
    runner = get_job_runner()
    record = runner.get_job(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Job not found or expired")
    return record.to_dict()
