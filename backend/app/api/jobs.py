"""Jobs API — query status of background jobs."""

from fastapi import APIRouter, HTTPException

from ..services.job_runner import get_job_runner

router = APIRouter()


@router.get("/")
async def list_jobs():
    """List all tracked background jobs (running + recently completed)."""
    runner = get_job_runner()
    return [job.to_dict() for job in runner.list_jobs()]


@router.get("/{job_id}")
async def get_job(job_id: str):
    """Get status of a specific background job."""
    runner = get_job_runner()
    record = runner.get_job(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Job not found or expired")
    return record.to_dict()
