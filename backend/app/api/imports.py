"""Imports API (ADR-018, design/ingestion.md §7).

The client describes files (manifest), seals the manifest (server-side
grouping), then supplies bytes one file at a time. The ingest worker processes
items as their bytes arrive; the client only observes and issues actions.

Every mutating endpoint is ``@write_locked`` (``BEGIN IMMEDIATE`` up front) so
it can't fail on a stale snapshot while the worker commits.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import shutil
import time
import uuid
from datetime import timedelta
from pathlib import Path, PurePosixPath
from typing import cast

import anyio
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...pipeline import ingest_queue as q
from ...pipeline.ingest_archive import expand_archive
from ...pipeline.ingest_worker import get_ingest_worker
from ..config import settings
from ..models import ImportGroup, ImportItem, ImportJob, get_session_local
from ..models.import_schemas import (
    ActionResult,
    ArchiveResult,
    ContentResult,
    CreateImportRequest,
    HashRequest,
    HashResponse,
    HashResult,
    ImageType,
    ImportCounts,
    ImportGroupSummary,
    ImportItemOut,
    ImportItemPage,
    ImportJobDetail,
    ImportJobList,
    ImportJobSummary,
    ItemActionRequest,
    JobStatus,
    ManifestItemResult,
    ManifestRequest,
    ManifestResponse,
    QueueStatus,
)
from ..services import ingest_state as st
from ..services.app_settings import get_settings as get_app_settings
from ..services.validation import verify_media_mime
from .dependencies import acquire_heavy_op, get_db, write_locked

logger = logging.getLogger(__name__)
router = APIRouter()

# An active job waiting on bytes that stopped arriving this long ago is shown as
# "upload interrupted".
UPLOAD_STALL = timedelta(minutes=2)
# Free space kept in reserve on top of an import's estimated needs at seal time.
SEAL_FREE_SPACE_MARGIN = 512 * 1024 * 1024
_STREAM_CHUNK = 256 * 1024


# Dependencies and helpers


def _open_session(request: Request) -> Session:
    return get_session_local(request.app.state.db_engine)()


def _job_or_404(db: Session, job_id: str) -> ImportJob:
    job = db.get(ImportJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Import not found")
    return job


def _require_unsealed(job: ImportJob) -> None:
    if job.planned_at is not None:
        raise HTTPException(status_code=409, detail="This import's file list is already sealed")


def _require_sealed(job: ImportJob) -> None:
    if job.planned_at is None:
        raise HTTPException(status_code=409, detail="Seal the import's file list first")


def _changed(wake: bool = False) -> None:
    worker = get_ingest_worker()
    worker.bump()
    if wake:
        worker.wake()


def _counts(by_state: dict[str, int]) -> ImportCounts:
    known = {state: by_state.get(state, 0) for state in st.ITEM_STATES}
    return ImportCounts(**known, total=sum(by_state.values()))


def _summaries(db: Session, jobs: list[ImportJob]) -> list[ImportJobSummary]:
    """Summaries for many jobs with two grouped queries (no per-job N+1)."""
    ids = [job.id for job in jobs]
    by_job: dict[str, dict[str, int]] = {job_id: {} for job_id in ids}
    group_counts: dict[str, int] = dict.fromkeys(ids, 0)
    if ids:
        rows = (
            db.query(ImportItem.job_id, ImportItem.state, func.count(ImportItem.id))
            .filter(ImportItem.job_id.in_(ids))
            .group_by(ImportItem.job_id, ImportItem.state)
        )
        for job_id, state, count in rows:
            by_job[job_id][state] = count
        group_rows = (
            db.query(ImportGroup.job_id, func.count(ImportGroup.id))
            .filter(ImportGroup.job_id.in_(ids))
            .group_by(ImportGroup.job_id)
            .tuples()
        )
        group_counts.update(dict(group_rows))
    now = q.utcnow()
    return [_summary(job, _counts(by_job[job.id]), group_counts[job.id], now) for job in jobs]


def _summary(job: ImportJob, counts: ImportCounts, group_count: int, now) -> ImportJobSummary:
    last_activity = job.last_upload_at or job.created_at or now
    interrupted = (
        job.status == st.JOB_ACTIVE
        and counts.awaiting_bytes > 0
        and counts.ready == 0
        and counts.processing == 0
        and now - last_activity > UPLOAD_STALL
    )
    return ImportJobSummary(
        id=job.id,
        label=job.source_label,
        status=cast(JobStatus, job.status),
        default_image_type=cast(ImageType, job.default_image_type),
        planned=job.planned_at is not None,
        dismissed=job.dismissed_at is not None,
        upload_interrupted=interrupted,
        counts=counts,
        group_count=group_count,
        created_at=job.created_at,
        updated_at=job.updated_at,
        completed_at=job.completed_at,
        last_upload_at=job.last_upload_at,
    )


def _detail(db: Session, job: ImportJob) -> ImportJobDetail:
    (summary,) = _summaries(db, [job])
    by_group: dict[int | None, dict[str, int]] = {}
    rows = (
        db.query(ImportItem.import_group_id, ImportItem.state, func.count(ImportItem.id))
        .filter(ImportItem.job_id == job.id)
        .group_by(ImportItem.import_group_id, ImportItem.state)
    )
    for group_id, state, count in rows:
        by_group.setdefault(group_id, {})[state] = count
    groups = (
        db.query(ImportGroup)
        .filter(ImportGroup.job_id == job.id)
        .order_by(ImportGroup.sort_order, ImportGroup.id)
        .all()
    )
    return ImportJobDetail(
        **summary.model_dump(),
        groups=[
            ImportGroupSummary(
                id=g.id,
                author=g.author,
                group_name=g.group_name,
                image_group_id=g.image_group_id,
                merged_into_existing=bool(g.merged_into_existing),
                sort_order=g.sort_order,
                counts=_counts(by_group.get(g.id, {})),
            )
            for g in groups
        ],
    )


def _queue_status() -> QueueStatus:
    status = get_ingest_worker().status()
    return QueueStatus(
        running=status.running,
        system_paused=status.system_paused,
        reason=status.system_reason,
        current_job_id=status.current_job_id,
    )


# Listing and detail


@router.post("/queue/probe", response_model=QueueStatus)
def probe_queue():
    """Re-check system conditions immediately ("Retry now" for a system pause)."""
    get_ingest_worker().probe_now()
    return _queue_status()


@router.get("", response_model=ImportJobList)
def list_imports(
    request: Request,
    response: Response,
    include_dismissed: bool = False,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """Job summaries for the activity dock, plus queue status.

    Supports ``If-None-Match``: the ETag changes whenever ingest state changes
    (and once a minute, for the time-derived "upload interrupted" flag), so
    idle polls cost almost nothing.
    """
    worker_status = get_ingest_worker().status()
    etag = f'W/"{worker_status.version}-{int(time.time() // 60)}-{int(include_dismissed)}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    response.headers["ETag"] = etag

    query = db.query(ImportJob)
    if not include_dismissed:
        query = query.filter(ImportJob.dismissed_at.is_(None))
    jobs = query.order_by(ImportJob.created_at.desc(), ImportJob.id).limit(limit).all()
    return ImportJobList(
        jobs=_summaries(db, jobs), queue=_queue_status(), version=worker_status.version
    )


@router.get("/{job_id}", response_model=ImportJobDetail)
def get_import(job_id: str, db: Session = Depends(get_db)):
    return _detail(db, _job_or_404(db, job_id))


@router.get("/{job_id}/items", response_model=ImportItemPage)
def list_items(
    job_id: str,
    state: list[str] | None = Query(None),
    group_id: int | None = None,
    error_kind: str | None = None,
    after: int = 0,
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    """Paginated per-file view for the import report (keyset pagination on id)."""
    _job_or_404(db, job_id)
    query = db.query(ImportItem).filter(ImportItem.job_id == job_id, ImportItem.id > after)
    if state:
        query = query.filter(ImportItem.state.in_(state))
    if group_id is not None:
        query = query.filter(ImportItem.import_group_id == group_id)
    if error_kind:
        query = query.filter(ImportItem.error_kind == error_kind)
    rows = query.order_by(ImportItem.id).limit(limit + 1).all()
    page = rows[:limit]
    return ImportItemPage(
        items=[ImportItemOut.model_validate(row) for row in page],
        next_after=page[-1].id if len(rows) > limit else None,
    )


# Create, manifest, archives, seal, hashes


@router.post("", response_model=ImportJobSummary, status_code=201)
@write_locked
def create_import(body: CreateImportRequest, db: Session = Depends(get_db)):
    job = q.create_job(db, label=body.label, default_image_type=body.default_image_type)
    db.commit()
    _changed()
    return _summaries(db, [job])[0]


@router.post("/{job_id}/manifest", response_model=ManifestResponse)
@write_locked
def add_manifest(job_id: str, body: ManifestRequest, db: Session = Depends(get_db)):
    """Add a chunk of file descriptions (metadata only, no bytes).

    Paths already in the job and OS junk are ignored. Unsupported files become
    skipped items and oversized ones failed items, so both show in the report.
    """
    job = _job_or_404(db, job_id)
    _require_unsealed(job)
    existing = db.query(func.count(ImportItem.id)).filter(ImportItem.job_id == job_id).scalar()
    if existing + len(body.files) > settings.max_import_items:
        raise HTTPException(
            status_code=413,
            detail=f"An import can contain at most {settings.max_import_items} files",
        )

    refs: dict[str, str | None] = {}
    entries = []
    for f in body.files:
        path = q.normalise_relative_path(f.relative_path)
        refs.setdefault(path, f.client_ref)
        entries.append(
            q.ManifestEntry(
                relative_path=f.relative_path,
                size=f.size,
                last_modified=f.last_modified,
                image_type=f.image_type,
            )
        )
    already = {
        path
        for (path,) in db.query(ImportItem.relative_path).filter(
            ImportItem.job_id == job_id, ImportItem.relative_path.in_(list(refs))
        )
    }
    app_settings = get_app_settings(db)
    items = q.add_manifest_items(
        db,
        job,
        [e for e in entries if q.normalise_relative_path(e.relative_path) not in already],
        max_file_size=app_settings.max_import_file_size,
    )
    db.commit()
    _changed()
    return ManifestResponse(
        items=[
            ManifestItemResult(
                client_ref=refs.get(item.relative_path),
                item_id=item.id,
                relative_path=item.relative_path,
                state=item.state,
                error_reason=item.error_reason,
            )
            for item in items
        ],
        ignored=len(body.files) - len(items),
    )


async def _stream_body(request: Request, dest: Path, max_bytes: int) -> tuple[int, str]:
    """Stream the request body to ``dest``, hashing as it goes. Returns (bytes, sha256)."""
    digest = hashlib.sha256()
    written = 0
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        async with await anyio.open_file(dest, "wb") as out:
            async for chunk in request.stream():
                written += len(chunk)
                if written > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File exceeds the {max_bytes // (1024 * 1024)} MB size limit",
                    )
                digest.update(chunk)
                await out.write(chunk)
    except BaseException:
        dest.unlink(missing_ok=True)
        raise
    return written, digest.hexdigest()


async def _drain(request: Request) -> None:
    async for _ in request.stream():
        pass


@router.put("/{job_id}/archives", response_model=ArchiveResult)
async def upload_archive(
    job_id: str,
    request: Request,
    name: str = Query(..., min_length=1, max_length=512),
    _admission: None = Depends(acquire_heavy_op),
):
    """Upload a zip (raw body); its contents become items. Only before seal."""

    def _limits():
        with _open_session(request) as db:
            job = _job_or_404(db, job_id)
            _require_unsealed(job)
            return get_app_settings(db)

    app_settings = await asyncio.to_thread(_limits)
    tmp = q.staging_dir_for(job_id) / f".{uuid.uuid4().hex}.zip.part"
    await _stream_body(request, tmp, app_settings.max_import_file_size)

    def _expand() -> ArchiveResult:
        db = _open_session(request)
        try:
            q.begin_immediate(db)
            job = _job_or_404(db, job_id)
            _require_unsealed(job)
            existing = db.query(func.count(ImportItem.id)).filter_by(job_id=job_id).scalar()
            counts = expand_archive(
                db,
                job,
                tmp,
                name,
                # The per-import item cap applies to archive members as well as manifests.
                max_files=min(app_settings.max_import_files, settings.max_import_items - existing),
                max_uncompressed_bytes=app_settings.max_import_total_size,
                max_file_size=app_settings.max_import_file_size,
            )
            job.last_upload_at = q.utcnow()
            db.commit()
            return ArchiveResult(name=name, **vars(counts))
        finally:
            tmp.unlink(missing_ok=True)
            db.close()

    result = await asyncio.to_thread(_expand)
    _changed()
    return result


def _check_free_space(db: Session, job_id: str) -> None:
    """Refuse to seal an import that can't fit on disk (staging + library copies)."""
    from ..services import get_image_store

    pending = (
        db.query(ImportItem.state, func.coalesce(func.sum(ImportItem.size), 0))
        .filter(
            ImportItem.job_id == job_id,
            ImportItem.state.in_([st.AWAITING_BYTES, st.READY]),
        )
        .group_by(ImportItem.state)
    )
    sizes = {state: size or 0 for state, size in pending}
    to_upload = sizes.get(st.AWAITING_BYTES, 0)
    to_store = to_upload + sizes.get(st.READY, 0)
    staging_root = settings.staging_dir
    staging_root.mkdir(parents=True, exist_ok=True)
    library_root = get_image_store().base_dir
    needs = {library_root: to_store}
    if os.stat(staging_root).st_dev == os.stat(library_root).st_dev:
        needs[library_root] += to_upload
    else:
        needs[staging_root] = to_upload
    for path, needed in needs.items():
        free = shutil.disk_usage(path).free
        if needed and free < needed + SEAL_FREE_SPACE_MARGIN:
            raise HTTPException(
                status_code=507,
                detail=(
                    f"Not enough free disk space: this import needs about "
                    f"{(needed + SEAL_FREE_SPACE_MARGIN) // (1024 * 1024)} MB on {path}, "
                    f"{free // (1024 * 1024)} MB available"
                ),
            )


@router.post("/{job_id}/seal", response_model=ImportJobDetail)
@write_locked
def seal_import(
    job_id: str,
    db: Session = Depends(get_db),
    _admission: None = Depends(acquire_heavy_op),
):
    """Close the file list: work out groups server-side and start processing. Idempotent."""
    job = _job_or_404(db, job_id)
    if job.planned_at is None:
        _check_free_space(db, job_id)
        q.plan_job(db, job_id)
        db.commit()
        _changed(wake=True)
    return _detail(db, job)


@router.post("/{job_id}/hashes", response_model=HashResponse)
@write_locked
def submit_hashes(job_id: str, body: HashRequest, db: Session = Depends(get_db)):
    """Client-computed SHA-256s, sent ahead of uploading; known files are skipped."""
    _job_or_404(db, job_id)
    items = q.apply_client_hashes(db, job_id, {e.item_id: e.sha256 for e in body.items})
    db.commit()
    _changed()
    return HashResponse(
        items=[
            HashResult(
                item_id=item.id,
                state=item.state,
                duplicate_of_image_id=item.duplicate_of_image_id,
            )
            for item in items
        ]
    )


# Bytes

_ALREADY_RECEIVED = frozenset({st.READY, st.PROCESSING, st.DONE, st.DUPLICATE})


def _content_result(item: ImportItem) -> ContentResult:
    return ContentResult(
        item_id=item.id,
        state=item.state,
        error_reason=item.error_reason,
        duplicate_of_image_id=item.duplicate_of_image_id,
    )


@router.put("/{job_id}/items/{item_id}/content", response_model=ContentResult)
async def upload_content(job_id: str, item_id: int, request: Request):
    """Upload one file's bytes (raw body). Idempotent and safe to retry.

    Re-sending bytes for an item that already has them is a no-op. The upload is
    streamed to a temp file, hashed, checked against its claimed type, then
    renamed into staging.
    """

    def _load():
        with _open_session(request) as db:
            job = _job_or_404(db, job_id)
            item = db.get(ImportItem, item_id)
            if item is None or item.job_id != job_id:
                raise HTTPException(status_code=404, detail="Item not found")
            app_settings = get_app_settings(db)
            limit = (
                app_settings.max_video_file_size
                if item.kind == "video"
                else app_settings.max_import_file_size
            )
            return job.status, item.state, item.relative_path, item.kind, limit, item

    job_status, state, relative_path, kind, limit, snapshot = await asyncio.to_thread(_load)
    if state in _ALREADY_RECEIVED:
        await _drain(request)
        return _content_result(snapshot)
    if state != st.AWAITING_BYTES or kind == "archive":
        await _drain(request)
        raise HTTPException(status_code=409, detail=f"This file can't accept an upload ({state})")
    if job_status == st.JOB_CANCELLED:
        await _drain(request)
        raise HTTPException(status_code=409, detail="This import was cancelled")

    ext = PurePosixPath(relative_path).suffix.lower()
    staging_key = f"{uuid.uuid4().hex}{ext}"
    final = q.staged_path(job_id, staging_key)
    tmp = final.with_name(f".{staging_key}.part")
    written, digest = await _stream_body(request, tmp, limit)
    if written == 0:
        tmp.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Empty upload")
    valid = await asyncio.to_thread(verify_media_mime, tmp, ext)

    def _record() -> ContentResult:
        db = _open_session(request)
        try:
            q.begin_immediate(db)
            item = db.get_one(ImportItem, item_id)
            if item.state != st.AWAITING_BYTES:  # a concurrent retry won the race
                tmp.unlink(missing_ok=True)
                return _content_result(item)
            problem = None
            if not valid:
                problem = "File content doesn't match its type"
            elif item.size is not None and item.size != written:
                problem = "File changed size after it was chosen; choose it again"
            if problem:
                tmp.unlink(missing_ok=True)
                item.state = st.next_item_state(item.state, st.ItemEvent.FILE_ERROR)
                item.error_kind = "file"
                item.error_stage = "validate"
                item.error_reason = problem
                q.recompute_job_status(db, job_id)
            else:
                os.replace(tmp, final)
                q.mark_bytes_received(db, item, staging_key=staging_key, source_hash=digest)
            db.commit()
            return _content_result(item)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        finally:
            db.close()

    result = await asyncio.to_thread(_record)
    _changed(wake=result.state == st.READY)
    return result


# Actions


def _action(db: Session, job_id: str, affected: int, wake: bool = False) -> ActionResult:
    db.commit()
    _changed(wake=wake)
    return ActionResult(affected=affected, status=db.get_one(ImportJob, job_id).status)


@router.post("/{job_id}/pause", response_model=ActionResult)
@write_locked
def pause_import(job_id: str, db: Session = Depends(get_db)):
    _job_or_404(db, job_id)
    q.pause_job(db, job_id)
    return _action(db, job_id, 0)


@router.post("/{job_id}/resume", response_model=ActionResult)
@write_locked
def resume_import(job_id: str, db: Session = Depends(get_db)):
    _job_or_404(db, job_id)
    q.resume_job(db, job_id)
    return _action(db, job_id, 0, wake=True)


@router.post("/{job_id}/cancel", response_model=ActionResult)
@write_locked
def cancel_import(job_id: str, db: Session = Depends(get_db)):
    """Stop the import. Finished files are kept; use DELETE to undo the import."""
    _job_or_404(db, job_id)
    return _action(db, job_id, q.cancel_job(db, job_id))


@router.post("/{job_id}/retry", response_model=ActionResult)
@write_locked
def retry_import_items(
    job_id: str, body: ItemActionRequest | None = None, db: Session = Depends(get_db)
):
    job = _job_or_404(db, job_id)
    if job.status == st.JOB_CANCELLED:
        raise HTTPException(status_code=409, detail="This import was cancelled")
    item_ids = body.item_ids if body else None
    return _action(db, job_id, q.retry_items(db, job_id, item_ids), wake=True)


@router.post("/{job_id}/import-as-copy", response_model=ActionResult)
@write_locked
def import_duplicates_as_copies(
    job_id: str, body: ItemActionRequest | None = None, db: Session = Depends(get_db)
):
    """Process duplicates as fully independent new images (design §6)."""
    job = _job_or_404(db, job_id)
    if job.status == st.JOB_CANCELLED:
        raise HTTPException(status_code=409, detail="This import was cancelled")
    item_ids = body.item_ids if body else None
    return _action(db, job_id, q.import_as_copy(db, job_id, item_ids), wake=True)


@router.post("/{job_id}/finish-upload", response_model=ActionResult)
@write_locked
def finish_without_missing(job_id: str, db: Session = Depends(get_db)):
    """Give up on files that were never uploaded."""
    job = _job_or_404(db, job_id)
    _require_sealed(job)
    affected = q.skip_items(db, job_id, "Not uploaded", states={st.AWAITING_BYTES})
    return _action(db, job_id, affected)


@router.post("/{job_id}/groups/{group_id}/skip", response_model=ActionResult)
@write_locked
def skip_group(job_id: str, group_id: int, db: Session = Depends(get_db)):
    _job_or_404(db, job_id)
    group = db.get(ImportGroup, group_id)
    if group is None or group.job_id != job_id:
        raise HTTPException(status_code=404, detail="Group not found")
    affected = q.skip_items(db, job_id, "Skipped", import_group_id=group_id)
    return _action(db, job_id, affected)


@router.post("/{job_id}/dismiss", response_model=ActionResult)
@write_locked
def dismiss_import(job_id: str, db: Session = Depends(get_db)):
    """Hide a finished import from the activity dock. Deletes nothing."""
    job = _job_or_404(db, job_id)
    if job.status not in (st.JOB_COMPLETED, st.JOB_CANCELLED):
        raise HTTPException(status_code=409, detail="Only finished imports can be dismissed")
    q.dismiss_job(db, job_id)
    return _action(db, job_id, 0)


@router.delete("/{job_id}", response_model=ActionResult)
@write_locked
def undo_import(job_id: str, db: Session = Depends(get_db)):
    """Undo: delete every image this import created, then the import itself."""
    _job_or_404(db, job_id)
    try:
        deleted, pending = q.undo_job(db, job_id)
    except q.JobBusyError:
        db.commit()  # keep the cancellation; the in-flight batch finishes shortly
        _changed()
        raise HTTPException(
            status_code=409, detail="Finishing the current batch; try again in a moment"
        ) from None
    except IntegrityError:
        db.rollback()
        raise
    db.commit()
    pending.apply()
    _changed()
    return ActionResult(affected=deleted, status="deleted")
