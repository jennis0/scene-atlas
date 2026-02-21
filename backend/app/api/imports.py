"""Import API endpoints for web-based image upload and processing.

Upload endpoint saves files to staging, then submits an analyse_upload
Prefect deployment to parse and group files. Confirm endpoint submits a
process_import_group deployment for async processing. Status endpoint
reads progress from the ImportJob table (updated by the flow).
"""

import json
import logging
import shutil
import uuid
import zipfile
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from prefect.deployments import run_deployment
from sqlalchemy.orm import Session

from ..config import settings
from ..models import (
    ImportGroupJob,
    ImportJob,
    get_session_local,
)
from ..models.schemas import (
    ImportConfirmFile,
    ImportConfirmRequest,
    ImportFileInfo,
    ImportGroupStatus,
    ImportJobResponse,
    ImportUploadResponse,
    ImportVariantGroup,
)

logger = logging.getLogger(__name__)

router = APIRouter()

def get_db(request: Request):
    """Dependency to get database session."""
    SessionLocal = get_session_local(request.app.state.db_engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/upload", response_model=ImportUploadResponse)
async def upload_files(
    request: Request,
    files: List[UploadFile] = File(...),
    relative_paths: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Upload files for import, analyse and group them.

    Accepts multiple image files and/or .zip archives.
    Saves to staging, submits analyse_upload Prefect flow,
    returns detected variant groups with metadata for user review.
    """
    job_id = uuid.uuid4().hex[:16]
    staging_dir = settings.staging_dir / job_id
    staging_dir.mkdir(parents=True, exist_ok=True)

    # Parse relative paths if provided
    rel_paths_list: list[str] = []
    if relative_paths:
        try:
            rel_paths_list = json.loads(relative_paths)
        except (json.JSONDecodeError, TypeError):
            rel_paths_list = []

    saved_relative_paths: list[str] = []

    try:
        for i, upload_file in enumerate(files):
            filename = upload_file.filename or f"file_{i}"

            # Use provided relative path if available, otherwise just filename
            rel_path = rel_paths_list[i] if i < len(rel_paths_list) else filename

            if filename.lower().endswith(".zip"):
                # Extract zip into staging dir
                zip_path = staging_dir / filename
                content = await upload_file.read()
                zip_path.write_bytes(content)

                with zipfile.ZipFile(zip_path, "r") as zf:
                    for member in zf.infolist():
                        # Skip directories, macOS resource forks, hidden files
                        if member.is_dir():
                            continue
                        if "__MACOSX" in member.filename or Path(member.filename).name.startswith("._"):
                            continue
                        # Only extract supported image formats
                        ext = Path(member.filename).suffix.lower()
                        if ext not in settings.supported_formats:
                            continue

                        zf.extract(member, staging_dir)
                        saved_relative_paths.append(member.filename)

                # Remove the zip file after extraction
                zip_path.unlink()
            else:
                # Regular image file
                ext = Path(filename).suffix.lower()
                if ext not in settings.supported_formats:
                    continue

                # Save file preserving relative path structure
                dest = staging_dir / rel_path
                dest.parent.mkdir(parents=True, exist_ok=True)
                content = await upload_file.read()
                dest.write_bytes(content)
                saved_relative_paths.append(rel_path)

        if not saved_relative_paths:
            # Clean up empty staging dir
            shutil.rmtree(staging_dir, ignore_errors=True)
            raise HTTPException(status_code=400, detail="No supported image files found in upload")

        # Submit analyse_upload flow via Prefect deployment (waits for result)
        logger.info(f"Submitting analyse_upload deployment for {len(saved_relative_paths)} files")
        flow_run = await run_deployment(
            name=f"{settings.analyse_flow}/{settings.analyse_deployment}",
            parameters={
                "staging_dir": str(staging_dir),
                "relative_paths": saved_relative_paths,
            },
            timeout=120,  # Wait up to 2 minutes for analysis
        )

        # Get the result from the completed flow
        if flow_run.state.is_failed():
            raise HTTPException(
                status_code=500,
                detail="File analysis failed. Check Prefect UI for details.",
            )

        groups = await flow_run.state.result()

        # Build response from flow result
        variant_groups: list[ImportVariantGroup] = []
        for group in groups:
            files_info: list[ImportFileInfo] = []
            for f in group["files"]:
                parsed = f["parsed"]
                files_info.append(ImportFileInfo(
                    relative_path=f["relative_path"],
                    filename=parsed["filename"],
                    detected_tags=[
                        {"category": t["category"], "value": t["value"],
                         "confidence": t.get("confidence", 1.0), "source": t.get("source", "auto")}
                        for t in parsed.get("tags", [])
                    ],
                    gridded=parsed.get("gridded"),
                    grid_width=parsed.get("grid_width"),
                    grid_height=parsed.get("grid_height"),
                    sub_variant=parsed.get("sub_variant"),
                ))

            variant_groups.append(ImportVariantGroup(
                author=group.get("author"),
                variant_group_name=group["variant_group_name"],
                files=files_info,
            ))

        # Create ImportJob in staging state
        import_job = ImportJob(
            id=job_id,
            status="staging",
            total_files=len(saved_relative_paths),
        )
        db.add(import_job)
        db.commit()

        return ImportUploadResponse(
            job_id=job_id,
            total_files=len(saved_relative_paths),
            variant_groups=variant_groups,
        )

    except HTTPException:
        raise
    except Exception as e:
        # Clean up on error
        shutil.rmtree(staging_dir, ignore_errors=True)
        logger.error(f"Upload failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")


@router.post("/{job_id}/confirm")
async def confirm_import(
    job_id: str,
    body: ImportConfirmRequest,
    db: Session = Depends(get_db),
):
    """Confirm a variant group for processing.

    Submits a process_import_group Prefect deployment and returns immediately.
    The flow updates ImportJob progress as it processes each image.
    """
    job = db.query(ImportJob).filter(ImportJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Import job not found")

    staging_dir = settings.staging_dir / job_id
    if not staging_dir.exists():
        raise HTTPException(status_code=404, detail="Staging directory not found")

    # Validate files exist and build serializable metadata list
    valid_files: list[dict] = []
    for file_info in body.files:
        if (staging_dir / file_info.relative_path).exists():
            valid_files.append(file_info.model_dump())
        else:
            logger.warning(f"File not found in staging: {file_info.relative_path}")

    if not valid_files:
        raise HTTPException(status_code=400, detail="No valid files to process")

    # Create an ImportGroupJob row to track this group's progress independently
    group_job_id = uuid.uuid4().hex[:16]
    group_job = ImportGroupJob(
        id=group_job_id,
        job_id=job_id,
        variant_group_name=body.variant_group_name,
        author=body.author,
        total_files=len(valid_files),
        processed_files=0,
        failed_files=0,
        status="running",
    )
    db.add(group_job)

    # Submit process_import_group flow via Prefect deployment (fire-and-forget)
    logger.info(
        f"Submitting process_import_group deployment for job {job_id}, "
        f"group_job {group_job_id}: {len(valid_files)} files, group '{body.variant_group_name}'"
    )
    flow_run = await run_deployment(
        name=f"{settings.process_flow}/{settings.process_deployment}",
        parameters={
            "job_id": job_id,
            "group_job_id": group_job_id,
            "staging_dir": str(staging_dir),
            "author": body.author,
            "variant_group_name": body.variant_group_name,
            "files": valid_files,
        },
        timeout=0,  # Return immediately, don't wait for completion
    )

    group_job.flow_run_id = str(flow_run.id)
    job.status = "running"
    db.commit()

    return ImportJobResponse(
        job_id=job.id,
        status="running",
        groups=[ImportGroupStatus(
            variant_group_name=body.variant_group_name,
            total_files=len(valid_files),
            processed_files=0,
            failed_files=0,
            status="running",
        )],
        created_at=job.created_at,
        completed_at=None,
    )


@router.get("/{job_id}/status", response_model=ImportJobResponse)
async def get_import_status(
    job_id: str,
    db: Session = Depends(get_db),
):
    """Get the status of an import job.

    Reads progress from the ImportJob table, which is updated by the
    process_import_group Prefect flow as it processes each image.
    """
    job = db.query(ImportJob).filter(ImportJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Import job not found")

    group_jobs = (
        db.query(ImportGroupJob)
        .filter(ImportGroupJob.job_id == job_id)
        .order_by(ImportGroupJob.created_at)
        .all()
    )

    groups = [
        ImportGroupStatus(
            variant_group_name=gj.variant_group_name,
            total_files=gj.total_files,
            processed_files=gj.processed_files,
            failed_files=gj.failed_files,
            status=gj.status,
        )
        for gj in group_jobs
    ]

    # Derive overall job status from group statuses
    if group_jobs:
        terminal = {"completed", "failed"}
        if all(gj.status in terminal for gj in group_jobs):
            overall_status = "completed"
        elif any(gj.status == "running" for gj in group_jobs):
            overall_status = "running"
        else:
            overall_status = job.status
    else:
        overall_status = job.status

    return ImportJobResponse(
        job_id=job.id,
        status=overall_status,
        groups=groups,
        created_at=job.created_at,
        completed_at=job.completed_at,
    )


@router.get("/{job_id}/preview/{relative_path:path}")
async def get_preview_thumbnail(
    job_id: str,
    relative_path: str,
):
    """Serve a preview thumbnail for a staged file.

    Thumbnails are pre-generated during the analyse_upload flow and stored
    in data/staging/{job_id}/.thumbs/. Falls back to the original staged
    file if no thumbnail exists.
    """
    staging_dir = settings.staging_dir / job_id
    if not staging_dir.exists():
        raise HTTPException(status_code=404, detail="Staging directory not found")

    # Convert relative_path to safe thumbnail filename
    safe_name = relative_path.replace("/", "__").replace("\\", "__")
    safe_name = Path(safe_name).stem + ".jpg"
    thumb_path = staging_dir / ".thumbs" / safe_name

    if thumb_path.exists():
        # Path traversal guard
        resolved = thumb_path.resolve()
        if not str(resolved).startswith(str(staging_dir.resolve())):
            raise HTTPException(status_code=403, detail="Access denied")
        return FileResponse(thumb_path, media_type="image/jpeg")

    # Fall back to original file
    original_path = staging_dir / relative_path
    if original_path.exists():
        resolved = original_path.resolve()
        if not str(resolved).startswith(str(staging_dir.resolve())):
            raise HTTPException(status_code=403, detail="Access denied")
        suffix = original_path.suffix.lower()
        media_types = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
        return FileResponse(original_path, media_type=media_types.get(suffix, "image/jpeg"))

    raise HTTPException(status_code=404, detail="Preview not found")
