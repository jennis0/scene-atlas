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

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..config import settings
from ..models import (
    Image,
    ImageGroup,
    ImportGroupJob,
    ImportJob,
)
from ..models.schemas import (
    ActiveImportsResponse,
    AnalyseRequest,
    BatchUploadResponse,
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
    ManifestEntry,
)
from ..services.app_settings import get_settings as get_app_settings
from ..services.job_runner import get_job_runner
from ..services.validation import check_zip_safety, is_path_within, verify_media_mime
from .dependencies import get_db


class ImportConfirmAllRequest(BaseModel):
    """Confirm all groups for processing in one flow run."""

    groups: list[ImportConfirmRequest]


VALID_IMAGE_TYPES = {"battlemap", "scene"}

logger = logging.getLogger(__name__)


def _parse_file_errors(raw: str | None) -> list[dict]:
    """Parse JSON file_errors column, returning empty list on any failure."""
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return parsed
    except (json.JSONDecodeError, TypeError):
        logger.warning("Malformed file_errors JSON in ImportGroupJob: %s", raw[:200])
    return []


router = APIRouter()


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

    The job starts in ``"uploading"`` status.  Call ``POST /{job_id}/upload-batch``
    one or more times to stage files, then ``POST /{job_id}/analyse`` to run
    group detection.  If the user closes the dialog mid-upload the HTTP
    requests continue in the background and the tray can track progress via
    this record.
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
    logger.info("Initialized import job %s (uploading)", job_id)
    return {"job_id": job_id}


async def _save_files_to_staging(
    files: list[UploadFile],
    rel_paths_list: list[str],
    staging_dir: Path,
    app_settings,
) -> tuple[list[str], int, list[str]]:
    """Save uploaded files to the staging directory.

    Handles both regular image/video files and ZIP archives.
    Validates file types, sizes, and magic bytes.

    Returns:
        (saved_relative_paths, total_bytes, skipped_invalid)
    """
    saved_relative_paths: list[str] = []
    # Calculate bytes already staged from previous batches so the cross-batch
    # total size limit cannot be bypassed by splitting a large upload into many
    # small batches.
    existing_bytes = sum(p.stat().st_size for p in staging_dir.rglob("*") if p.is_file())
    total_upload_bytes = existing_bytes
    skipped_invalid: list[str] = []

    for i, upload_file in enumerate(files):
        filename = upload_file.filename or f"file_{i}"
        rel_path = rel_paths_list[i] if i < len(rel_paths_list) else filename

        if filename.lower().endswith(".zip"):
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
                    if member.is_dir():
                        continue
                    if "__MACOSX" in member.filename or Path(member.filename).name.startswith(
                        "._"
                    ):
                        continue
                    ext = Path(member.filename).suffix.lower()
                    if ext not in settings.all_supported_formats:
                        continue
                    zf.extract(member, staging_dir)
                    saved_relative_paths.append(member.filename)

            zip_path.unlink()
        else:
            ext = Path(filename).suffix.lower()
            if ext not in settings.all_supported_formats:
                continue

            is_video = ext in settings.supported_video_formats
            file_size_limit = (
                app_settings.max_video_file_size if is_video else app_settings.max_import_file_size
            )

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

            if not verify_media_mime(content, ext):
                logger.warning("Skipping invalid file (bad magic bytes): %s", filename)
                skipped_invalid.append(filename)
                continue

            dest = staging_dir / rel_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(content)
            saved_relative_paths.append(rel_path)

    return saved_relative_paths, total_upload_bytes, skipped_invalid


def _build_analysis_response(
    groups: list[dict],
    job: ImportJob,
    all_relative_paths: list[str],
    db: Session,
) -> ImportUploadResponse:
    """Map analyse_upload output to ImportUploadResponse and persist job state."""
    import_groups: list[ImportGroup] = []
    for group in groups:
        files_info: list[ImportFileInfo] = []
        for f in group["files"]:
            parsed = f["parsed"]
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

    source_label = import_groups[0].group_name if import_groups else None
    analysis_data = {
        "summary": [
            {"group_name": g.group_name, "author": g.author, "file_count": len(g.files)}
            for g in import_groups
        ],
        "groups": [g.model_dump() for g in import_groups],
    }

    job.status = "staging"
    job.source_label = source_label
    job.total_files = len(all_relative_paths)
    job.analysis_result = json.dumps(analysis_data)
    job.pending_groups = len(import_groups)
    job.updated_at = datetime.now(UTC).replace(tzinfo=None)
    db.commit()

    return ImportUploadResponse(
        job_id=job.id,
        total_files=len(all_relative_paths),
        groups=import_groups,
    )


@router.post("/{job_id}/upload-batch", response_model=BatchUploadResponse)
async def upload_batch(
    job_id: str,
    files: list[UploadFile] = File(default=[]),
    relative_paths: str | None = Form(None),
    db: Session = Depends(get_db),
):
    """Upload one batch of files to staging for an existing import job.

    Call this endpoint multiple times (one batch at a time) before calling
    ``POST /{job_id}/analyse`` to trigger group detection.  This avoids
    hitting timeout limits when uploading large numbers of files.

    Each batch should be bounded to a manageable size (e.g. ≤20 files or
    ≤100 MB).  Files are appended to the staging directory; the job status
    remains ``"uploading"`` until ``/analyse`` is called.
    """
    job = db.query(ImportJob).filter(ImportJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Import job not found")
    if job.status != "uploading":
        raise HTTPException(
            status_code=409,
            detail=f"Import job is in '{job.status}' state, expected 'uploading'",
        )

    staging_dir = settings.staging_dir / job_id
    staging_dir.mkdir(parents=True, exist_ok=True)

    rel_paths_list: list[str] = []
    if relative_paths:
        try:
            rel_paths_list = json.loads(relative_paths)
        except (json.JSONDecodeError, TypeError):
            rel_paths_list = []

    app_settings = get_app_settings(db)

    if len(files) > app_settings.max_import_files:
        raise HTTPException(
            status_code=413,
            detail=f"Too many files in batch: {len(files)}, limit is {app_settings.max_import_files}",
        )

    try:
        saved_paths, total_bytes, skipped_invalid = await _save_files_to_staging(
            files, rel_paths_list, staging_dir, app_settings
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Batch upload failed for job %s: %s", job_id, e)
        raise HTTPException(status_code=500, detail=f"Batch upload failed: {e}") from e

    logger.info(
        "Batch upload for job %s: %d files saved (%d bytes), %d skipped",
        job_id,
        len(saved_paths),
        total_bytes,
        len(skipped_invalid),
    )
    return BatchUploadResponse(
        files_saved=len(saved_paths),
        bytes_saved=total_bytes,
        skipped_invalid=skipped_invalid,
    )


@router.post("/{job_id}/analyse", response_model=ImportUploadResponse)
async def analyse_staged(
    job_id: str,
    body: AnalyseRequest,
    db: Session = Depends(get_db),
):
    """Analyse all staged files and transition job to 'staging' state.

    Call this after all ``/upload-batch`` requests have completed.
    Scans the staging directory for saved files, merges with the duplicate
    manifest, runs group detection, and returns the same response shape as
    the old ``/upload`` endpoint.
    """
    job = db.query(ImportJob).filter(ImportJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Import job not found")
    if job.status != "uploading":
        raise HTTPException(
            status_code=409,
            detail=f"Import job is in '{job.status}' state, expected 'uploading'",
        )

    staging_dir = settings.staging_dir / job_id
    if not staging_dir.exists():
        raise HTTPException(status_code=400, detail="No staged files found for this job")

    if body.image_type not in VALID_IMAGE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid image_type '{body.image_type}'. Must be one of: {', '.join(sorted(VALID_IMAGE_TYPES))}",
        )

    # Discover all files already saved in staging (skip thumbnail cache dir)
    saved_relative_paths: list[str] = []
    thumbs_dir = staging_dir / ".thumbs"
    for path in staging_dir.rglob("*"):
        if path.is_dir():
            continue
        # Skip thumbnail cache and macOS artefacts
        try:
            path.relative_to(thumbs_dir)
            continue
        except ValueError:
            pass
        if path.name.startswith("._") or "__MACOSX" in path.parts:
            continue
        ext = path.suffix.lower()
        if ext not in settings.all_supported_formats:
            continue
        saved_relative_paths.append(str(path.relative_to(staging_dir)))

    # Merge with manifest (duplicate files the client chose not to re-upload)
    manifest_entries: list[ManifestEntry] = body.manifest
    manifest_paths = [entry.relative_path for entry in manifest_entries]
    all_relative_paths = saved_relative_paths + manifest_paths

    if not all_relative_paths:
        raise HTTPException(
            status_code=400,
            detail="No supported image or video files found in staging",
        )

    precomputed_hashes: dict[str, dict] = {
        entry.relative_path: {
            "content_hash": entry.content_hash,
            "duplicate_of": entry.duplicate_of,
        }
        for entry in manifest_entries
    }

    from ...pipeline.ingestion import analyse_upload

    runner = get_job_runner()
    logger.info(
        "Running analyse_upload for job %s: %d staged + %d manifest files",
        job_id,
        len(saved_relative_paths),
        len(manifest_entries),
    )
    try:
        groups = runner.run_sync(
            analyse_upload,
            staging_dir=str(staging_dir),
            relative_paths=all_relative_paths,
            precomputed_hashes=precomputed_hashes if precomputed_hashes else None,
            default_image_type=body.image_type,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"File analysis failed: {e}") from e

    return _build_analysis_response(groups, job, all_relative_paths, db)


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
            logger.warning(
                "File not found in staging and no reuse key: %s", file_info.relative_path
            )

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
        "Submitting process_import_group for job %s, group_job %s: %s files, group '%s'",
        job_id,
        group_job_id,
        len(valid_files),
        body.group_name,
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

    # Sync pending groups from frontend (handles merge/split correctly)
    job.pending_groups = len(body.remaining_groups)
    job.status = "active"
    job.updated_at = datetime.now(UTC).replace(tzinfo=None)
    db.commit()

    return ImportJobResponse(
        job_id=job.id,
        status="active",
        groups=[
            ImportGroupStatus(
                group_job_id=group_job_id,
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
            logger.warning("No valid files for group '%s', skipping", group_req.group_name)
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
                group_job_id=group_job_id,
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
    job.pending_groups = 0
    job.updated_at = datetime.now(UTC).replace(tzinfo=None)
    db.commit()

    logger.info("Submitted process_import_job for job %s: %s groups", job_id, len(groups_payload))

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
            group_job_id=gj.id,
            group_name=gj.group_name,
            total_files=gj.total_files,
            processed_files=gj.processed_files,
            failed_files=gj.failed_files,
            status=gj.status,
            group_id=gj.created_group_id,
            file_errors=_parse_file_errors(gj.file_errors),
        )
        for gj in group_jobs
    ]

    # Status is authoritative from DB — no derivation needed
    return ImportJobResponse(
        job_id=job.id,
        status=job.status,
        groups=groups,
        detected_group_count=job.pending_groups + len(group_jobs),
        pending_group_count=job.pending_groups,
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

    Returns staging/active/awaiting_input jobs and recently-completed ones
    (within 1 hour). Status is authoritative from the ImportJob table.
    """
    from datetime import timedelta

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

        # Status is authoritative from DB — no derivation needed
        truly_terminal = {"completed", "failed", "cancelled", "expired"}
        if job.status in truly_terminal:
            if job.completed_at is None or job.completed_at < cutoff:
                continue

        summaries.append(
            ImportJobSummary(
                job_id=job.id,
                source_label=job.source_label,
                status=job.status,
                total_groups=job.pending_groups + len(groups),
                completed_groups=sum(1 for g in groups if g.status == "completed"),
                failed_groups=sum(1 for g in groups if g.status == "failed"),
                running_groups=sum(1 for g in groups if g.status == "running"),
                pending_groups=job.pending_groups,
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
    # Only delete jobs in terminal status — status is authoritative from DB
    terminal_statuses = {"completed", "failed", "cancelled", "expired", "broken"}

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

    # User is declaring they're done — clear pending groups and compute final status
    job.pending_groups = 0

    groups = db.query(ImportGroupJob).filter(ImportGroupJob.job_id == job_id).all()
    if groups:
        from ..services.import_state import transition_job_status

        transition_job_status(db, job_id)
    else:
        # No groups were ever confirmed — just mark completed
        job.status = "completed"
        job.completed_at = datetime.now(UTC).replace(tzinfo=None)

    staging_dir = settings.staging_dir / job_id
    staging_cleaned = False
    if staging_dir.exists():
        shutil.rmtree(staging_dir, ignore_errors=True)
        staging_cleaned = True

    db.commit()
    logger.info(
        "Import job %s finalized as '%s' (staging_cleaned=%s)", job_id, job.status, staging_cleaned
    )
    return {"status": job.status, "staging_cleaned": staging_cleaned, "already_terminal": False}


def _cleanup_import_images(job_id: str, db: Session) -> int:
    """Delete all Image rows created by this import job.

    For each image, checks if its storage_key is shared with other Image rows.
    If not shared, deletes the physical file and thumbnail from disk.
    Also removes embeddings from Qdrant (best-effort) and deletes now-empty
    ImageGroups that were created by this import.

    Returns the count of Image rows deleted.
    """
    from ..services import get_image_store, get_thumbnail_store
    from ..services.qdrant_service import get_qdrant_service

    images = db.query(Image).filter(Image.import_job_id == job_id).all()
    if not images:
        return 0

    image_store = get_image_store()
    thumbnail_store = get_thumbnail_store()
    qdrant = get_qdrant_service()
    deleted_count = 0
    image_ids_to_delete = []
    group_ids_to_check = set()

    for image in images:
        image_ids_to_delete.append(image.id)
        if image.group_id:
            group_ids_to_check.add(image.group_id)

        # Only delete physical files when no other Image row shares this storage_key
        sibling_count = (
            db.query(Image)
            .filter(Image.storage_key == image.storage_key, Image.id != image.id)
            .count()
        )
        if sibling_count == 0:
            if image.storage_key:
                image_store.delete(image.storage_key)
            if image.thumbnail_key:
                thumbnail_store.delete(image.thumbnail_key)

        db.delete(image)
        deleted_count += 1

    # Remove Qdrant embeddings (best-effort, non-fatal)
    if image_ids_to_delete:
        try:
            qdrant.delete_embeddings(image_ids_to_delete)
        except Exception:
            logger.warning(
                "Qdrant cleanup failed for job %s (non-fatal)", job_id, exc_info=True
            )

    db.flush()

    # Delete now-empty ImageGroups that were created by this import
    group_job_rows = (
        db.query(ImportGroupJob.created_group_id)
        .filter(ImportGroupJob.job_id == job_id, ImportGroupJob.created_group_id.isnot(None))
        .all()
    )
    created_group_ids = {row[0] for row in group_job_rows}

    for group_id in created_group_ids & group_ids_to_check:
        remaining = db.query(Image).filter(Image.group_id == group_id).count()
        if remaining == 0:
            grp = db.query(ImageGroup).filter(ImageGroup.id == group_id).first()
            if grp:
                db.delete(grp)

    return deleted_count


@router.post("/{job_id}/cancel")
async def cancel_import(job_id: str, db: Session = Depends(get_db)):
    """Cancel an import job and clean up all associated data.

    Deletes:
    - Staging directory
    - All Image rows created by this import (files on disk if not shared with
      other imports, thumbnails, Qdrant embeddings)
    - Now-empty ImageGroups created by this import

    Works for all non-completed states. Returns 409 for completed imports.
    """
    job = db.query(ImportJob).filter(ImportJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Import job not found")

    if job.status == "completed":
        raise HTTPException(
            status_code=409,
            detail="Cannot cancel a completed import. Use the delete endpoint to remove images.",
        )

    # Clean up imported images (files + DB rows + Qdrant vectors)
    deleted_images = _cleanup_import_images(job_id, db)
    logger.info("Deleted %d image(s) for cancelled import %s", deleted_images, job_id)

    # Clean up staging directory
    staging_dir = settings.staging_dir / job_id
    if staging_dir.exists():
        shutil.rmtree(staging_dir, ignore_errors=True)

    # Mark all group jobs as cancelled
    db.query(ImportGroupJob).filter(ImportGroupJob.job_id == job_id).update(
        {"status": "cancelled"},
        synchronize_session=False,
    )

    # Mark job as cancelled
    now = datetime.now(UTC).replace(tzinfo=None)
    job.status = "cancelled"
    job.completed_at = now
    job.updated_at = now
    job.pending_groups = 0
    db.commit()

    return {
        "status": "cancelled",
        "deleted_images": deleted_images,
        "staging_cleaned": True,
    }


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
