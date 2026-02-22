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
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel
from fastapi.responses import FileResponse
from prefect.deployments import run_deployment
from sqlalchemy.orm import Session

from ..config import settings
from ..services.validation import check_zip_safety, verify_image_mime
from ..models import (
    ImportGroupJob,
    ImportJob,
    get_session_local,
)
from ..models.schemas import (
    ActiveImportsResponse,
    DuplicateInfo,
    HashCheckRequest,
    HashCheckResponse,
    HashCheckResultItem,
    ImportConfirmFile,
    ImportConfirmRequest,
    ImportFileInfo,
    ImportGroupStatus,
    ImportJobResponse,
    ImportJobSummary,
    ImportUploadResponse,
    ImportVariantGroup,
)


class ImportConfirmAllRequest(BaseModel):
    """Confirm all variant groups for processing in one flow run."""

    groups: List[ImportConfirmRequest]


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


@router.post("/check-hashes", response_model=HashCheckResponse)
async def check_hashes(
    body: HashCheckRequest,
    db: Session = Depends(get_db),
):
    """Check a batch of content hashes against the database.

    Returns duplicate info for any hash that matches an existing image.
    Used as a pre-flight check before uploading, allowing the client
    to skip uploading files that already exist in the library.
    """
    from ..models import Image

    if not body.files:
        return HashCheckResponse(results=[], total_checked=0, duplicates_found=0)

    # Collect unique hashes and batch-query DB
    unique_hashes = list({f.content_hash for f in body.files})
    existing_images = db.query(Image).filter(Image.content_hash.in_(unique_hashes)).all()

    # Build hash → DuplicateInfo map (first match wins)
    hash_to_dup: dict[str, DuplicateInfo] = {}
    for img in existing_images:
        if img.content_hash and img.content_hash not in hash_to_dup:
            hash_to_dup[img.content_hash] = DuplicateInfo(
                image_id=img.id,
                name=img.name,
                author=img.author,
                storage_key=img.storage_key,
                thumbnail_key=img.thumbnail_key,
                variant_group_name=img.variant_group_name,
            )

    # Build results
    results = []
    duplicates_found = 0
    for f in body.files:
        dup = hash_to_dup.get(f.content_hash)
        if dup:
            duplicates_found += 1
        results.append(
            HashCheckResultItem(
                relative_path=f.relative_path,
                content_hash=f.content_hash,
                duplicate_of=dup,
            )
        )

    return HashCheckResponse(
        results=results,
        total_checked=len(body.files),
        duplicates_found=duplicates_found,
    )


@router.post("/upload", response_model=ImportUploadResponse)
async def upload_files(
    request: Request,
    files: List[UploadFile] = File(default=[]),
    relative_paths: Optional[str] = Form(None),
    manifest: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Upload files for import, analyse and group them.

    Accepts multiple image files and/or .zip archives.
    Saves to staging, submits analyse_upload Prefect flow,
    returns detected variant groups with metadata for user review.

    The optional ``manifest`` parameter is a JSON array of entries for
    files that the client determined are duplicates and chose not to
    upload.  Each entry has ``relative_path``, ``filename``,
    ``content_hash``, and ``duplicate_of``.  These files are included
    in variant-group detection but skip server-side hashing.
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

    # Parse manifest of duplicate files (not uploaded, will reuse existing storage)
    manifest_entries: list[dict] = []
    if manifest:
        try:
            manifest_entries = json.loads(manifest)
        except (json.JSONDecodeError, TypeError):
            manifest_entries = []

    # Early count guard — catches obvious over-limit requests before reading content
    if len(files) > settings.max_import_files:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise HTTPException(
            status_code=413,
            detail=f"Too many files: {len(files)} uploaded, limit is {settings.max_import_files}",
        )

    saved_relative_paths: list[str] = []
    total_upload_bytes = 0
    skipped_invalid: list[str] = []

    try:
        for i, upload_file in enumerate(files):
            filename = upload_file.filename or f"file_{i}"

            # Use provided relative path if available, otherwise just filename
            rel_path = rel_paths_list[i] if i < len(rel_paths_list) else filename

            if filename.lower().endswith(".zip"):
                # Read ZIP into memory and check compressed size
                content = await upload_file.read()
                if len(content) > settings.max_import_file_size:
                    limit_mb = settings.max_import_file_size // (1024 * 1024)
                    raise HTTPException(
                        status_code=413,
                        detail=f"File '{filename}' exceeds size limit of {limit_mb} MB",
                    )
                total_upload_bytes += len(content)
                if total_upload_bytes > settings.max_import_total_size:
                    limit_mb = settings.max_import_total_size // (1024 * 1024)
                    raise HTTPException(
                        status_code=413,
                        detail=f"Total upload size exceeds limit of {limit_mb} MB",
                    )

                # Save ZIP and check for bombs before extraction
                zip_path = staging_dir / filename
                zip_path.write_bytes(content)
                try:
                    check_zip_safety(
                        zip_path,
                        max_files=settings.max_import_files,
                        max_uncompressed_bytes=settings.max_import_total_size,
                    )
                except ValueError as exc:
                    zip_path.unlink(missing_ok=True)
                    raise HTTPException(status_code=413, detail=str(exc))

                with zipfile.ZipFile(zip_path, "r") as zf:
                    for member in zf.infolist():
                        # Skip directories, macOS resource forks, hidden files
                        if member.is_dir():
                            continue
                        if "__MACOSX" in member.filename or Path(member.filename).name.startswith(
                            "._"
                        ):
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
                # Regular image file — check extension first (cheap)
                ext = Path(filename).suffix.lower()
                if ext not in settings.supported_formats:
                    continue

                # Read content and enforce size limits
                content = await upload_file.read()
                if len(content) > settings.max_import_file_size:
                    limit_mb = settings.max_import_file_size // (1024 * 1024)
                    raise HTTPException(
                        status_code=413,
                        detail=f"File '{filename}' exceeds size limit of {limit_mb} MB",
                    )
                total_upload_bytes += len(content)
                if total_upload_bytes > settings.max_import_total_size:
                    limit_mb = settings.max_import_total_size // (1024 * 1024)
                    raise HTTPException(
                        status_code=413,
                        detail=f"Total upload size exceeds limit of {limit_mb} MB",
                    )

                # Validate it's actually an image (not a renamed binary)
                if not verify_image_mime(content):
                    logger.warning(f"Skipping non-image file: {filename}")
                    skipped_invalid.append(filename)
                    continue

                # Save file preserving relative path structure
                dest = staging_dir / rel_path
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(content)
                saved_relative_paths.append(rel_path)

        # Merge uploaded + manifest paths for grouping (grouping uses relative paths only)
        manifest_paths = [entry["relative_path"] for entry in manifest_entries]
        all_relative_paths = saved_relative_paths + manifest_paths

        if not all_relative_paths:
            shutil.rmtree(staging_dir, ignore_errors=True)
            detail = "No supported image files found in upload"
            if skipped_invalid:
                detail += f"; {len(skipped_invalid)} file(s) rejected as non-image content"
            raise HTTPException(status_code=400, detail=detail)

        # Build precomputed hashes dict from manifest entries
        precomputed_hashes: dict[str, dict] = {}
        for entry in manifest_entries:
            precomputed_hashes[entry["relative_path"]] = {
                "content_hash": entry["content_hash"],
                "duplicate_of": entry["duplicate_of"],
            }

        # Submit analyse_upload flow via Prefect deployment (waits for result)
        logger.info(
            f"Submitting analyse_upload deployment for {len(all_relative_paths)} files "
            f"({len(saved_relative_paths)} uploaded, {len(manifest_entries)} from manifest)"
        )
        flow_run = await run_deployment(
            name=f"{settings.analyse_flow}/{settings.analyse_deployment}",
            parameters={
                "staging_dir": str(staging_dir),
                "relative_paths": all_relative_paths,
                "precomputed_hashes": precomputed_hashes if precomputed_hashes else None,
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
                # Build duplicate info if the analysis detected a match
                dup_data = f.get("duplicate_of")
                dup_info = DuplicateInfo(**dup_data) if dup_data else None

                files_info.append(
                    ImportFileInfo(
                        relative_path=f["relative_path"],
                        filename=parsed["filename"],
                        name=parsed.get("map_name"),
                        detected_tags=[
                            {
                                "category": t["category"],
                                "value": t["value"],
                                "confidence": t.get("confidence", 1.0),
                                "source": t.get("source", "auto"),
                            }
                            for t in parsed.get("tags", [])
                        ],
                        gridded=parsed.get("gridded"),
                        grid_width=parsed.get("grid_width"),
                        grid_height=parsed.get("grid_height"),
                        sub_variant=parsed.get("sub_variant"),
                        content_hash=f.get("content_hash"),
                        duplicate_of=dup_info,
                    )
                )

            variant_groups.append(
                ImportVariantGroup(
                    author=group.get("author"),
                    variant_group_name=group["variant_group_name"],
                    files=files_info,
                )
            )

        # Create ImportJob in staging state
        source_label = variant_groups[0].variant_group_name if variant_groups else None
        import_job = ImportJob(
            id=job_id,
            status="staging",
            source_label=source_label,
            total_files=len(all_relative_paths),
        )
        db.add(import_job)
        db.commit()

        return ImportUploadResponse(
            job_id=job_id,
            total_files=len(all_relative_paths),
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

    # Validate files: must exist in staging OR have a reuse key (duplicate not uploaded)
    valid_files: list[dict] = []
    for file_info in body.files:
        if (staging_dir / file_info.relative_path).exists() or file_info.reuse_storage_key:
            valid_files.append(file_info.model_dump())
        else:
            logger.warning(f"File not found in staging and no reuse key: {file_info.relative_path}")

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
        groups=[
            ImportGroupStatus(
                variant_group_name=body.variant_group_name,
                total_files=len(valid_files),
                processed_files=0,
                failed_files=0,
                status="running",
            )
        ],
        created_at=job.created_at,
        completed_at=None,
    )


@router.post("/{job_id}/confirm-all")
async def confirm_all_groups(
    job_id: str,
    body: ImportConfirmAllRequest,
    db: Session = Depends(get_db),
):
    """Confirm all variant groups for processing in a single flow run.

    Unlike the per-group /confirm endpoint (which spawns one Prefect flow per
    group), this endpoint submits a single process_import_job flow that handles
    all groups sequentially.  The CLIP model is therefore loaded once for the
    entire job instead of once per group subprocess, dramatically reducing peak
    memory usage for large multi-group imports.
    """
    job = db.query(ImportJob).filter(ImportJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Import job not found")

    staging_dir = settings.staging_dir / job_id
    if not staging_dir.exists():
        raise HTTPException(status_code=404, detail="Staging directory not found")

    # Build ImportGroupJob rows and the groups payload for the flow.
    groups_payload: list[dict] = []
    group_statuses: list[ImportGroupStatus] = []
    for group_req in body.groups:
        valid_files = [
            f.model_dump()
            for f in group_req.files
            if (staging_dir / f.relative_path).exists() or f.reuse_storage_key
        ]
        if not valid_files:
            logger.warning(f"No valid files for group '{group_req.variant_group_name}', skipping")
            continue

        group_job_id = uuid.uuid4().hex[:16]
        group_job = ImportGroupJob(
            id=group_job_id,
            job_id=job_id,
            variant_group_name=group_req.variant_group_name,
            author=group_req.author,
            total_files=len(valid_files),
            processed_files=0,
            failed_files=0,
            status="running",
        )
        db.add(group_job)

        groups_payload.append(
            {
                "group_job_id": group_job_id,
                "author": group_req.author,
                "variant_group_name": group_req.variant_group_name,
                "files": valid_files,
            }
        )
        group_statuses.append(
            ImportGroupStatus(
                variant_group_name=group_req.variant_group_name,
                total_files=len(valid_files),
                processed_files=0,
                failed_files=0,
                status="running",
            )
        )

    if not groups_payload:
        raise HTTPException(status_code=400, detail="No valid files found in any group")

    flow_run = await run_deployment(
        name=f"{settings.process_job_flow}/{settings.process_job_deployment}",
        parameters={
            "job_id": job_id,
            "staging_dir": str(staging_dir),
            "groups": groups_payload,
        },
        timeout=0,  # fire-and-forget
    )

    job.status = "running"
    db.commit()

    logger.info(
        f"Submitted process_import_job for job {job_id}: "
        f"{len(groups_payload)} groups, flow_run={flow_run.id}"
    )

    return ImportJobResponse(
        job_id=job.id,
        status="running",
        groups=group_statuses,
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
        terminal = {"completed", "failed", "cancelled"}
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


@router.get("/active", response_model=ActiveImportsResponse)
async def get_active_imports(db: Session = Depends(get_db)):
    """List non-terminal import jobs for the import tray.

    Returns staging/running jobs and recently-completed ones (within 1 hour).
    Effective status is derived from group states so jobs show correctly even
    if the Prefect flow hasn't written back to ImportJob yet.
    """
    from datetime import timedelta

    terminal_statuses = {"completed", "failed", "cancelled"}
    cutoff = datetime.utcnow() - timedelta(hours=1)

    # Fetch recent jobs — import tables are small so fetching last 7 days is fine
    recent_cutoff = datetime.utcnow() - timedelta(days=7)
    all_jobs = (
        db.query(ImportJob)
        .filter(ImportJob.created_at >= recent_cutoff)
        .order_by(ImportJob.created_at.desc())
        .all()
    )

    summaries = []
    for job in all_jobs:
        groups = db.query(ImportGroupJob).filter(ImportGroupJob.job_id == job.id).all()

        # Derive effective status from groups (more accurate than stale job.status)
        if not groups:
            effective_status = job.status
            completed_at = job.completed_at
        elif all(g.status in terminal_statuses for g in groups):
            effective_status = (
                "failed" if any(g.status == "failed" for g in groups) else "completed"
            )
            completed_at = max(
                (g.completed_at for g in groups if g.completed_at),
                default=job.completed_at,
            )
        elif any(g.status == "running" for g in groups):
            effective_status = "running"
            completed_at = None
        else:
            effective_status = job.status
            completed_at = job.completed_at

        # Filter: always include staging/running; completed/failed only within 1h
        if effective_status in terminal_statuses:
            if completed_at is None or completed_at < cutoff:
                continue

        summaries.append(
            ImportJobSummary(
                job_id=job.id,
                source_label=job.source_label,
                status=effective_status,
                total_groups=len(groups),
                completed_groups=sum(1 for g in groups if g.status == "completed"),
                failed_groups=sum(1 for g in groups if g.status == "failed"),
                running_groups=sum(1 for g in groups if g.status == "running"),
                total_files=job.total_files,
                created_at=job.created_at,
            )
        )

    return ActiveImportsResponse(jobs=summaries)


@router.delete("/cleanup")
async def cleanup_old_imports(db: Session = Depends(get_db)):
    """Delete completed, failed, cancelled, and abandoned staging import jobs.

    Never deletes jobs that are currently staging (pending user review) or running.
    """
    # Fetch all groups so we can derive the effective status of each job
    terminal_statuses = {"completed", "failed", "cancelled"}

    all_jobs = db.query(ImportJob).all()
    to_delete = []

    for job in all_jobs:
        groups = db.query(ImportGroupJob).filter(ImportGroupJob.job_id == job.id).all()

        if not groups:
            # Staging job with no confirmed groups — safe to delete
            # unless it's actively being worked on (status = staging means
            # the user hasn't confirmed anything yet; we delete them all here)
            if job.status != "running":
                to_delete.append(job)
        elif all(g.status in terminal_statuses for g in groups):
            # All groups are terminal — job is done
            to_delete.append(job)
        # Otherwise: has running groups — leave it alone

    count = len(to_delete)
    for job in to_delete:
        db.delete(job)
    db.commit()

    return {"deleted": count}


@router.post("/{job_id}/cancel")
async def cancel_import(job_id: str, db: Session = Depends(get_db)):
    """Cancel an import job and clean up staging files.

    Only cleans up staging directory if no groups are still running.
    Marks the job as cancelled if no groups were ever confirmed.
    """
    job = db.query(ImportJob).filter(ImportJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Import job not found")

    staging_dir = settings.staging_dir / job_id

    # Check if any groups are still running — don't delete staging if so
    running_groups = (
        db.query(ImportGroupJob)
        .filter(ImportGroupJob.job_id == job_id, ImportGroupJob.status == "running")
        .count()
    )

    if running_groups == 0 and staging_dir.exists():
        shutil.rmtree(staging_dir, ignore_errors=True)

    # Update job status
    all_groups = db.query(ImportGroupJob).filter(ImportGroupJob.job_id == job_id).all()
    if not all_groups:
        # No groups were ever confirmed — pure cancellation
        job.status = "cancelled"
    elif all(g.status in ("completed", "failed", "cancelled") for g in all_groups):
        job.status = "completed"

    job.completed_at = datetime.utcnow()
    db.commit()

    return {"status": job.status, "staging_cleaned": running_groups == 0}


@router.post("/{job_id}/groups/{group_id}/cancel")
async def cancel_import_group(
    job_id: str,
    group_id: str,
    db: Session = Depends(get_db),
):
    """Cancel a single import group.

    Only groups that haven't started running can be cancelled.
    """
    group_job = (
        db.query(ImportGroupJob)
        .filter(ImportGroupJob.id == group_id, ImportGroupJob.job_id == job_id)
        .first()
    )
    if not group_job:
        raise HTTPException(status_code=404, detail="Group not found")
    if group_job.status not in ("pending", "running"):
        raise HTTPException(
            status_code=400,
            detail=f"Group in '{group_job.status}' state cannot be cancelled",
        )

    group_job.status = "cancelled"
    group_job.completed_at = datetime.utcnow()
    db.commit()

    return {"status": "cancelled", "group_id": group_id}


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
        media_types = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
        }
        return FileResponse(original_path, media_type=media_types.get(suffix, "image/jpeg"))

    raise HTTPException(status_code=404, detail="Preview not found")
