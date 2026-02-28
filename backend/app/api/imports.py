"""Import API endpoints for web-based image upload and processing.

Upload endpoint saves files to staging, then calls analyse_upload to parse
and group files. Confirm endpoint submits processing to the background
JobRunner. Status endpoint reads progress from the ImportJob table.
"""

import json
import logging
import shutil
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..config import settings
from ..models import (
    ImportGroupJob,
    ImportJob,
)
from ..models.schemas import (
    ActiveImportsResponse,
    DuplicateInfo,
    HashCheckRequest,
    HashCheckResponse,
    HashCheckResultItem,
    ImportConfirmRequest,
    ImportFileInfo,
    ImportGroup,
    ImportGroupStatus,
    ImportJobResponse,
    ImportJobSummary,
    ImportUploadResponse,
)
from ..services.app_settings import get_settings as get_app_settings
from ..services.job_runner import get_job_runner
from ..services.validation import check_zip_safety, is_path_within, verify_media_mime
from .dependencies import get_db


class ImportConfirmAllRequest(BaseModel):
    """Confirm all groups for processing in one flow run."""

    groups: list[ImportConfirmRequest]


logger = logging.getLogger(__name__)

router = APIRouter()


def _get_detected_group_count(job: ImportJob) -> int:
    """Parse the analysis_result JSON to get the number of initially detected groups."""
    if not job.analysis_result:
        return 0
    try:
        parsed = json.loads(job.analysis_result)
        if isinstance(parsed, dict):
            return len(parsed.get("summary", []))
        return len(parsed)  # Legacy format (plain list)
    except (json.JSONDecodeError, TypeError):
        return 0


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
                group_name=img.group_name,
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


@router.post("/init")
async def init_import(db: Session = Depends(get_db)):
    """Create an ImportJob immediately so the frontend can persist the job_id.

    The job starts in ``"uploading"`` status.  The subsequent ``/upload``
    call should pass the returned ``job_id`` so that the upload is attached
    to this pre-created job.  If the user closes the dialog mid-upload the
    HTTP request continues in the background, and the tray can track the job
    via this record.
    """
    job_id = uuid.uuid4().hex[:16]
    staging_dir = settings.staging_dir / job_id
    staging_dir.mkdir(parents=True, exist_ok=True)
    import_job = ImportJob(
        id=job_id,
        status="uploading",
    )
    db.add(import_job)
    db.commit()
    logger.info(f"Initialized import job {job_id} (uploading)")
    return {"job_id": job_id}


@router.post("/upload", response_model=ImportUploadResponse)
async def upload_files(
    request: Request,
    files: list[UploadFile] = File(default=[]),
    relative_paths: str | None = Form(None),
    manifest: str | None = Form(None),
    image_type: str | None = Form(None),
    job_id: str | None = Form(None),
    db: Session = Depends(get_db),
):
    """Upload files for import, analyse and group them.

    Accepts multiple image files and/or .zip archives.
    Saves to staging, runs analyse_upload synchronously,
    returns detected groups with metadata for user review.

    The optional ``job_id`` parameter allows attaching the upload to a
    pre-created job (from ``POST /init``).  If omitted, a new job is
    created inline (backward compatibility).

    The optional ``manifest`` parameter is a JSON array of entries for
    files that the client determined are duplicates and chose not to
    upload.  Each entry has ``relative_path``, ``filename``,
    ``content_hash``, and ``duplicate_of``.  These files are included
    in group detection but skip server-side hashing.
    """
    # Use pre-created job or create inline
    existing_job: ImportJob | None = None
    if job_id:
        existing_job = db.query(ImportJob).filter(ImportJob.id == job_id).first()
        if not existing_job:
            raise HTTPException(status_code=404, detail="Import job not found")
        if existing_job.status != "uploading":
            raise HTTPException(
                status_code=409,
                detail=f"Import job is in '{existing_job.status}' state, expected 'uploading'",
            )
        staging_dir = settings.staging_dir / job_id
        staging_dir.mkdir(parents=True, exist_ok=True)
    else:
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

    # Validate image_type if provided
    VALID_IMAGE_TYPES = {"battlemap", "scene"}
    if image_type and image_type not in VALID_IMAGE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid image_type '{image_type}'. Must be one of: {', '.join(sorted(VALID_IMAGE_TYPES))}",
        )

    # Read import limits from DB-backed settings
    app_settings = get_app_settings(db)

    # Early count guard — catches obvious over-limit requests before reading content
    if len(files) > app_settings.max_import_files:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise HTTPException(
            status_code=413,
            detail=f"Too many files: {len(files)} uploaded, limit is {app_settings.max_import_files}",
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
                if len(content) > app_settings.max_import_file_size:
                    limit_mb = app_settings.max_import_file_size // (1024 * 1024)
                    raise HTTPException(
                        status_code=413,
                        detail=f"File '{filename}' exceeds size limit of {limit_mb} MB",
                    )
                total_upload_bytes += len(content)
                if total_upload_bytes > app_settings.max_import_total_size:
                    limit_mb = app_settings.max_import_total_size // (1024 * 1024)
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
                        max_files=app_settings.max_import_files,
                        max_uncompressed_bytes=app_settings.max_import_total_size,
                    )
                except ValueError as exc:
                    zip_path.unlink(missing_ok=True)
                    raise HTTPException(status_code=413, detail=str(exc)) from exc

                with zipfile.ZipFile(zip_path, "r") as zf:
                    for member in zf.infolist():
                        # Skip directories, macOS resource forks, hidden files
                        if member.is_dir():
                            continue
                        if "__MACOSX" in member.filename or Path(member.filename).name.startswith(
                            "._"
                        ):
                            continue
                        # Only extract supported image/video formats
                        ext = Path(member.filename).suffix.lower()
                        if ext not in settings.all_supported_formats:
                            continue

                        zf.extract(member, staging_dir)
                        saved_relative_paths.append(member.filename)

                # Remove the zip file after extraction
                zip_path.unlink()
            else:
                # Regular image/video file — check extension first (cheap)
                ext = Path(filename).suffix.lower()
                if ext not in settings.all_supported_formats:
                    continue

                # Apply per-type size limit
                is_video = ext in settings.supported_video_formats
                file_size_limit = (
                    app_settings.max_video_file_size
                    if is_video
                    else app_settings.max_import_file_size
                )

                # Read content and enforce size limits
                content = await upload_file.read()
                if len(content) > file_size_limit:
                    limit_mb = file_size_limit // (1024 * 1024)
                    raise HTTPException(
                        status_code=413,
                        detail=f"File '{filename}' exceeds size limit of {limit_mb} MB",
                    )
                total_upload_bytes += len(content)
                if total_upload_bytes > app_settings.max_import_total_size:
                    limit_mb = app_settings.max_import_total_size // (1024 * 1024)
                    raise HTTPException(
                        status_code=413,
                        detail=f"Total upload size exceeds limit of {limit_mb} MB",
                    )

                # Validate it's actually an image/video (not a renamed binary)
                if not verify_media_mime(content, ext):
                    logger.warning(f"Skipping invalid file (bad magic bytes): {filename}")
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
            detail = "No supported image or video files found in upload"
            if skipped_invalid:
                detail += f"; {len(skipped_invalid)} file(s) rejected (invalid content)"
            raise HTTPException(status_code=400, detail=detail)

        # Build precomputed hashes dict from manifest entries
        precomputed_hashes: dict[str, dict] = {}
        for entry in manifest_entries:
            precomputed_hashes[entry["relative_path"]] = {
                "content_hash": entry["content_hash"],
                "duplicate_of": entry["duplicate_of"],
            }

        # Run analyse_upload synchronously (fast — no CLIP, just filename parsing)
        logger.info(
            f"Running analyse_upload for {len(all_relative_paths)} files "
            f"({len(saved_relative_paths)} uploaded, {len(manifest_entries)} from manifest)"
        )
        from ...pipeline.ingestion import analyse_upload

        runner = get_job_runner()
        try:
            groups = runner.run_sync(
                analyse_upload,
                staging_dir=str(staging_dir),
                relative_paths=all_relative_paths,
                precomputed_hashes=precomputed_hashes if precomputed_hashes else None,
                default_image_type=image_type or "battlemap",
            )
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"File analysis failed: {e}",
            ) from e

        # Build response from flow result
        import_groups: list[ImportGroup] = []
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
                        name=parsed.get("name"),
                        media_type=(
                            "video"
                            if Path(f["relative_path"]).suffix.lower()
                            in settings.supported_video_formats
                            else "image"
                        ),
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
                        grid_type=parsed.get("grid_type"),
                        grid_width=parsed.get("grid_width"),
                        grid_height=parsed.get("grid_height"),
                        subgroup=parsed.get("subgroup"),
                        image_type=parsed.get("image_type"),
                        content_hash=f.get("content_hash"),
                        duplicate_of=dup_info,
                    )
                )

            import_groups.append(
                ImportGroup(
                    author=group.get("author"),
                    group_name=group["group_name"],
                    files=files_info,
                )
            )

        # Store full analysis (summary + groups) for reconnect support
        source_label = import_groups[0].group_name if import_groups else None
        analysis_data = {
            "summary": [
                {"group_name": g.group_name, "author": g.author, "file_count": len(g.files)}
                for g in import_groups
            ],
            "groups": [g.model_dump() for g in import_groups],
        }

        if existing_job:
            # Update pre-created job from init
            existing_job.status = "staging"
            existing_job.source_label = source_label
            existing_job.total_files = len(all_relative_paths)
            existing_job.analysis_result = json.dumps(analysis_data)
            existing_job.updated_at = datetime.now(UTC).replace(tzinfo=None)
        else:
            # Create new job inline (backward compat)
            import_job = ImportJob(
                id=job_id,
                status="staging",
                source_label=source_label,
                total_files=len(all_relative_paths),
                analysis_result=json.dumps(analysis_data),
            )
            db.add(import_job)
        db.commit()

        return ImportUploadResponse(
            job_id=job_id,
            total_files=len(all_relative_paths),
            groups=import_groups,
        )

    except HTTPException:
        raise
    except Exception as e:
        # Clean up on error
        shutil.rmtree(staging_dir, ignore_errors=True)
        logger.error(f"Upload failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}") from e


@router.post("/{job_id}/confirm")
async def confirm_import(
    job_id: str,
    body: ImportConfirmRequest,
    db: Session = Depends(get_db),
):
    """Confirm a group for processing.

    Submits process_import_group to the background JobRunner and returns immediately.
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
        group_name=body.group_name,
        author=body.author,
        total_files=len(valid_files),
        processed_files=0,
        failed_files=0,
        status="running",
    )
    db.add(group_job)

    # Submit process_import_group to background JobRunner (fire-and-forget)
    logger.info(
        f"Submitting process_import_group for job {job_id}, "
        f"group_job {group_job_id}: {len(valid_files)} files, group '{body.group_name}'"
    )
    from ...pipeline.ingestion import process_import_group
    from ...pipeline.pipeline_config import PipelineConfig

    _pipeline_config = PipelineConfig.from_app_settings(get_app_settings(db))

    runner = get_job_runner()
    runner.submit(
        process_import_group,
        job_id=job_id,
        group_job_id=group_job_id,
        staging_dir=str(staging_dir),
        author=body.author,
        group_name=body.group_name,
        files=valid_files,
        pipeline_config=_pipeline_config,
        name=f"Import: {body.group_name}",
    )

    job.status = "active"
    job.updated_at = datetime.now(UTC).replace(tzinfo=None)
    db.commit()

    return ImportJobResponse(
        job_id=job.id,
        status="active",
        groups=[
            ImportGroupStatus(
                group_name=body.group_name,
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
    """Confirm all groups for processing in a single flow run.

    Unlike the per-group /confirm endpoint (which submits one job per group),
    this endpoint submits a single process_import_job that handles all groups
    sequentially.  The CLIP model is therefore loaded once for the entire job
    instead of once per group, reducing peak memory usage for large multi-group
    imports.
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
            logger.warning(f"No valid files for group '{group_req.group_name}', skipping")
            continue

        group_job_id = uuid.uuid4().hex[:16]
        group_job = ImportGroupJob(
            id=group_job_id,
            job_id=job_id,
            group_name=group_req.group_name,
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
                "group_name": group_req.group_name,
                "files": valid_files,
            }
        )
        group_statuses.append(
            ImportGroupStatus(
                group_name=group_req.group_name,
                total_files=len(valid_files),
                processed_files=0,
                failed_files=0,
                status="running",
            )
        )

    if not groups_payload:
        raise HTTPException(status_code=400, detail="No valid files found in any group")

    from ...pipeline.ingestion import process_import_job
    from ...pipeline.pipeline_config import PipelineConfig

    _pipeline_config = PipelineConfig.from_app_settings(get_app_settings(db))

    runner = get_job_runner()
    runner.submit(
        process_import_job,
        job_id=job_id,
        staging_dir=str(staging_dir),
        groups=groups_payload,
        pipeline_config=_pipeline_config,
        name=f"Import job: {job_id[:8]}",
    )

    job.status = "active"
    job.all_confirmed = True
    job.updated_at = datetime.now(UTC).replace(tzinfo=None)
    db.commit()

    logger.info(f"Submitted process_import_job for job {job_id}: {len(groups_payload)} groups")

    return ImportJobResponse(
        job_id=job.id,
        status="active",
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
    process_import_group background job as it processes each image.
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
            group_name=gj.group_name,
            total_files=gj.total_files,
            processed_files=gj.processed_files,
            failed_files=gj.failed_files,
            status=gj.status,
            group_id=gj.created_group_id,
        )
        for gj in group_jobs
    ]

    # Compute detected/pending group counts from analysis_result
    detected_count = _get_detected_group_count(job)
    submitted_count = len(group_jobs)
    pending_count = max(0, detected_count - submitted_count)

    # Derive overall job status from group statuses
    if group_jobs:
        terminal = {"completed", "failed", "cancelled"}
        all_terminal = all(gj.status in terminal for gj in group_jobs)
        if all_terminal:
            if not job.all_confirmed and pending_count > 0:
                # Single-confirm path with unsubmitted groups: stay active
                overall_status = "active"
            else:
                overall_status = "completed"
        elif any(gj.status == "running" for gj in group_jobs):
            overall_status = "active"
        else:
            overall_status = job.status
    else:
        overall_status = job.status

    return ImportJobResponse(
        job_id=job.id,
        status=overall_status,
        groups=groups,
        detected_group_count=detected_count,
        pending_group_count=pending_count,
        created_at=job.created_at,
        completed_at=job.completed_at,
    )


@router.get("/{job_id}/analysis", response_model=ImportUploadResponse)
async def get_import_analysis(job_id: str, db: Session = Depends(get_db)):
    """Return the stored analysis for an import job.

    Used by the frontend to rebuild the preview UI when reconnecting to a job
    that was closed during upload (localStorage has no groups, but the server
    completed the analysis in the background).
    """
    job = db.query(ImportJob).filter(ImportJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Import job not found")
    if not job.analysis_result:
        raise HTTPException(status_code=404, detail="No analysis available")
    try:
        parsed = json.loads(job.analysis_result)
        # New format: dict with "groups" key; legacy format: plain list (no full groups)
        groups_data = parsed.get("groups", []) if isinstance(parsed, dict) else []
        if not groups_data:
            raise HTTPException(status_code=404, detail="No analysis available")
        groups = [ImportGroup(**g) for g in groups_data]
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        raise HTTPException(status_code=404, detail="Analysis data corrupted") from e
    return ImportUploadResponse(
        job_id=job_id,
        total_files=job.total_files or 0,
        groups=groups,
    )


@router.get("/active", response_model=ActiveImportsResponse)
async def get_active_imports(db: Session = Depends(get_db)):
    """List non-terminal import jobs for the import tray.

    Returns staging/running jobs and recently-completed ones (within 1 hour).
    Effective status is derived from group states so jobs show correctly even
    if the background job hasn't written back to ImportJob yet.
    """
    from datetime import timedelta

    terminal_statuses = {"completed", "failed", "cancelled"}
    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1)

    # Fetch recent jobs — import tables are small so fetching last 7 days is fine
    recent_cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=7)
    all_jobs = (
        db.query(ImportJob)
        .filter(ImportJob.created_at >= recent_cutoff)
        .order_by(ImportJob.created_at.desc())
        .all()
    )

    summaries = []
    for job in all_jobs:
        groups = db.query(ImportGroupJob).filter(ImportGroupJob.job_id == job.id).all()

        # Compute pending group count from analysis_result
        detected_count = _get_detected_group_count(job)
        submitted_count = len(groups)
        pending_count = max(0, detected_count - submitted_count)

        # Derive effective status from groups (more accurate than stale job.status)
        if not groups:
            effective_status = job.status
            completed_at = job.completed_at
        elif all(g.status in terminal_statuses for g in groups):
            if not job.all_confirmed and pending_count > 0:
                # Single-confirm with unsubmitted groups: stay active
                effective_status = "active"
                completed_at = None
            else:
                effective_status = (
                    "failed" if any(g.status == "failed" for g in groups) else "completed"
                )
                completed_at = max(
                    (g.completed_at for g in groups if g.completed_at),
                    default=job.completed_at,
                )
        elif any(g.status == "running" for g in groups):
            effective_status = "active"
            completed_at = None
        else:
            effective_status = job.status
            completed_at = job.completed_at

        # Filter: always include staging/active; terminal only within 1h
        truly_terminal = {"completed", "failed", "cancelled", "expired"}
        if effective_status in truly_terminal:
            if completed_at is None or completed_at < cutoff:
                continue

        summaries.append(
            ImportJobSummary(
                job_id=job.id,
                source_label=job.source_label,
                status=effective_status,
                total_groups=max(detected_count, len(groups)),
                completed_groups=sum(1 for g in groups if g.status == "completed"),
                failed_groups=sum(1 for g in groups if g.status == "failed"),
                running_groups=sum(1 for g in groups if g.status == "running"),
                pending_groups=pending_count,
                total_files=job.total_files,
                processed_files=sum(g.processed_files for g in groups),
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
    terminal_statuses = {"completed", "failed", "cancelled", "expired"}

    all_jobs = db.query(ImportJob).all()
    to_delete = []

    for job in all_jobs:
        groups = db.query(ImportGroupJob).filter(ImportGroupJob.job_id == job.id).all()

        if not groups:
            # Staging/expired job with no confirmed groups — safe to delete
            if job.status in terminal_statuses:
                to_delete.append(job)
        elif all(g.status in terminal_statuses for g in groups):
            # All groups are terminal — job is done (only delete if job itself is terminal)
            if job.status in terminal_statuses:
                to_delete.append(job)
        # Otherwise: has running groups or active job — leave it alone

    count = len(to_delete)
    for job in to_delete:
        db.delete(job)
    db.commit()

    return {"deleted": count}


@router.post("/{job_id}/finalize")
async def finalize_import(job_id: str, db: Session = Depends(get_db)):
    """Explicitly mark an import job as completed and clean up staging.

    Called by the frontend when the user is done submitting groups (single-
    confirm path).  For confirm-all, the job auto-completes — this endpoint
    is not needed.

    Returns 409 if groups are still running.  Idempotent for already-
    terminal jobs.
    """
    job = db.query(ImportJob).filter(ImportJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Import job not found")

    terminal = {"completed", "failed", "cancelled", "expired"}
    if job.status in terminal:
        return {"status": job.status, "staging_cleaned": False, "already_terminal": True}

    # Don't finalize while groups are still running
    running = (
        db.query(ImportGroupJob)
        .filter(ImportGroupJob.job_id == job_id, ImportGroupJob.status == "running")
        .count()
    )
    if running > 0:
        raise HTTPException(
            status_code=409, detail="Cannot finalize while groups are still processing"
        )

    groups = db.query(ImportGroupJob).filter(ImportGroupJob.job_id == job_id).all()
    has_failures = any(g.status == "failed" for g in groups)
    job.status = "failed" if has_failures else "completed"
    job.completed_at = datetime.now(UTC).replace(tzinfo=None)

    staging_dir = settings.staging_dir / job_id
    staging_cleaned = False
    if staging_dir.exists():
        shutil.rmtree(staging_dir, ignore_errors=True)
        staging_cleaned = True

    db.commit()
    logger.info(
        f"Import job {job_id} finalized as '{job.status}' (staging_cleaned={staging_cleaned})"
    )
    return {"status": job.status, "staging_cleaned": staging_cleaned, "already_terminal": False}


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

    job.completed_at = datetime.now(UTC).replace(tzinfo=None)
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
    group_job.completed_at = datetime.now(UTC).replace(tzinfo=None)
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
        if not is_path_within(staging_dir, thumb_path):
            raise HTTPException(status_code=403, detail="Access denied")
        return FileResponse(thumb_path, media_type="image/jpeg")

    # Fall back to original file
    original_path = staging_dir / relative_path
    if original_path.exists():
        if not is_path_within(staging_dir, original_path):
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
