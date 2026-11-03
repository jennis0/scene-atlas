"""Library identity and the linked folder (design/library-setup.md)."""

from datetime import UTC
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ...pipeline import export_library, library_move, library_rebuild, metadata_export
from ...pipeline import ingest_queue as q
from ...pipeline.db import pipeline_db
from ...pipeline.ingest_worker import get_ingest_worker
from ...pipeline.linked_scanner import get_linked_scanner
from ..config import settings
from ..library_identity import get_library_id, inside_any, inspect_folders
from ..models import LibrarySource
from ..models.database import SOURCE_DETACHED, SOURCE_OFFLINE, SOURCE_ONLINE
from ..models.schemas import (
    FullExportRequest,
    FullExportStarted,
    FullExportStatus,
    InspectHints,
    InspectLibrary,
    InspectLinked,
    InspectRequest,
    InspectResult,
    LibraryScanRequest,
    LibraryScanStarted,
    LibraryStatus,
    LinkedLibraryStatus,
    LinkedRemoved,
    MetadataExportRequest,
    MetadataExportStarted,
    MetadataExportStatus,
    MoveRequest,
    MoveStatus,
)
from ..services.app_settings import get_settings as get_app_settings
from ..services.job_runner import PURGE_JOB_NAME, get_job_runner
from ..services.linked_files import (
    count_linked,
    current_source,
    detach_source,
    linked_image_ids,
    linked_jobs_busy,
    missing_image_ids,
    open_linked_jobs,
    remove_images,
)
from ..services.originals import forget_availability, linked_folder_available
from .dependencies import acquire_heavy_op, get_db, write_locked
from .models import ACTIVATION_JOB_PREFIX
from .rate_limits import limiter
from .search import REBUILD_EMBEDDINGS_JOB

router = APIRouter()


def _absolute(raw: str | None) -> Path | None:
    if raw is None:
        return None
    path = Path(raw)
    if not path.is_absolute():
        raise HTTPException(status_code=422, detail=f"Not an absolute path: {raw}")
    return path


@router.post("/inspect", response_model=InspectResult)
def inspect_library(body: InspectRequest, _admission: None = Depends(acquire_heavy_op)):
    """What opening these folders as a library would do, for the setup wizard and
    Settings (desktop app only). Read-only; returns counts and marker contents, never
    file names. Counting a large maps folder can take seconds.

    Not available in server mode, where the client's paths would name the server's
    folders; there the folders come only from configuration.
    """
    if settings.app_mode != "app":
        raise HTTPException(status_code=404, detail="Not Found")
    found = inspect_folders(
        app_data=_absolute(body.app_data),
        store=_absolute(body.store),
        linked=_absolute(body.linked),
        max_items=settings.max_local_import_items,
    )
    linked = found.linked
    library = found.library
    return InspectResult(
        outcome=found.outcome,
        message=found.message,
        linked=InspectLinked(kind=linked.kind, image_count=linked.image_count, capped=linked.capped)
        if linked
        else None,
        library=InspectLibrary(
            library_id=library.library_id,
            setup_completed=library.setup_completed,
            hints=InspectHints(**library.hints),
        )
        if library
        else None,
        store_has_maps=found.store_has_maps,
    )


@router.get("/status", response_model=LibraryStatus)
def library_status(db: Session = Depends(get_db)):
    """The library's ID and its linked folder: configured, or detached (its images are
    still here but no folder is configured). Counts come from indexed queries."""
    library_id = get_library_id(db)
    if library_id is None:  # set at startup, so only a database swapped underneath us
        raise HTTPException(status_code=503, detail="The library isn't open")
    root = settings.linked_library_dir
    source = current_source(db)
    if root is not None:
        location = root
    elif source is not None:
        location = Path(source.location)
    else:
        return LibraryStatus(library_id=library_id, linked=None)
    if root is None or (source is not None and source.state == SOURCE_DETACHED):
        state = SOURCE_DETACHED
    else:
        state = SOURCE_ONLINE if linked_folder_available(fresh=True) else SOURCE_OFFLINE
    image_count, missing_count = count_linked(db, source.id) if source is not None else (0, 0)
    return LibraryStatus(
        library_id=library_id,
        linked=LinkedLibraryStatus(
            state=state,
            name=location.name or str(location),
            path=str(location) if settings.app_mode == "app" else None,
            image_count=image_count,
            missing_count=missing_count,
            # Stored naive in UTC; sent with its offset so browsers don't read it as local time.
            last_scan_at=(
                source.last_scan_at.replace(tzinfo=UTC)
                if source is not None and source.last_scan_at is not None
                else None
            ),
            scanning=get_linked_scanner().running,
        ),
    )


def _require_linked(db: Session) -> None:
    """409 unless a linked folder is configured and in use (not detached by "Unlink
    this folder" while the configuration still names it)."""
    source = current_source(db)
    if settings.linked_library_dir is None or (
        source is not None and source.state == SOURCE_DETACHED
    ):
        raise HTTPException(status_code=409, detail="No library is linked")


@router.post("/scan", status_code=202, response_model=LibraryScanStarted)
def scan_linked_folder(body: LibraryScanRequest, db: Session = Depends(get_db)):
    """Check the linked folder for changes, in the background. ``manual`` (Check for
    changes) runs unless a scan is running. ``focus`` (the desktop window regained focus)
    is ignored within a minute of the last scan, or when rescans are off."""
    _require_linked(db)
    if body.reason == "focus" and get_app_settings(db).linked_rescan_minutes == 0:
        return LibraryScanStarted(started=False)
    forget_availability()
    return LibraryScanStarted(started=get_linked_scanner().start(body.reason))


def _remove(db: Session, image_ids: list[int], detach: LibrarySource | None = None) -> int:
    pending = remove_images(db, image_ids)
    if detach is not None:
        detach_source(db, detach)
    db.commit()
    pending.apply()
    get_ingest_worker().bump()
    return len(image_ids)


@router.post("/linked/remove-missing", response_model=LinkedRemoved)
@write_locked
def remove_missing(db: Session = Depends(get_db)):
    """Remove the maps whose file is gone from the linked folder: rows, thumbnails and
    vectors. Their files are recorded as removed, so they aren't added again."""
    source = current_source(db)
    if source is None:
        return LinkedRemoved(removed=0)
    return LinkedRemoved(removed=_remove(db, missing_image_ids(db, source.id)))


@router.delete("/linked", response_model=LinkedRemoved)
@write_locked
def stop_using_linked_folder(db: Session = Depends(get_db)):
    """Unlink the linked folder: remove every map read from it and forget its files.
    The folder itself is never touched. The source is detached until the configuration
    drops the folder (the desktop app restarts; on a server, unset ``SCENE_ATLAS_LINKED_LIBRARY_DIR``).
    """
    source = current_source(db)
    if source is None:
        return LinkedRemoved(removed=0)
    if get_linked_scanner().running:
        raise HTTPException(
            status_code=409, detail="The linked library is being checked; try again"
        )
    for job in open_linked_jobs(db, source.id):
        q.cancel_job(db, job.id)
    if linked_jobs_busy(db, source.id):
        db.commit()  # keep the cancellation; the batch in progress finishes shortly
        get_ingest_worker().bump()
        raise HTTPException(
            status_code=409, detail="Finishing the current batch; try again in a moment"
        )
    return LinkedRemoved(removed=_remove(db, linked_image_ids(db, source.id), detach=source))


# Metadata export (design/export-backup-move.md §4)


# Jobs that rewrite the vectors: an export during one would mix two models' vectors.
_REEMBEDDING_JOBS = (REBUILD_EMBEDDINGS_JOB, ACTIVATION_JOB_PREFIX)


def _refuse_while_reembedding(runner) -> None:
    if any(
        job.status in ("queued", "running") and job.name.startswith(_REEMBEDDING_JOBS)
        for job in runner.list_jobs()
    ):
        raise HTTPException(
            status_code=409,
            detail="The search data is being rebuilt; export when that has finished",
        )


def _outside_library(path: Path) -> None:
    if inside_any(path, [settings.data_dir, settings.images_dir, settings.linked_library_dir]):
        raise HTTPException(status_code=422, detail="Save it outside the library's own folders")


def _export_target(raw: str | None) -> Path:
    """Where the export goes: the desktop app's chosen file, or the exports folder."""
    if raw is None:
        return settings.metadata_exports_dir / metadata_export.export_name()
    if settings.app_mode != "app":
        # In server mode a client-named path would name the server's own disk.
        raise HTTPException(status_code=422, detail="A path can only be given in the desktop app")
    path = Path(raw)
    if not path.is_absolute():
        raise HTTPException(status_code=422, detail=f"Not an absolute path: {raw}")
    if not path.parent.is_dir():
        raise HTTPException(status_code=422, detail=f"Folder not found: {path.parent}")
    if path.is_dir():
        raise HTTPException(status_code=422, detail=f"That's a folder: {path}")
    _outside_library(path)
    return path


@router.get("/metadata-export", response_model=MetadataExportStatus)
def metadata_export_status():
    """The export running now, if any, and (on a server) the newest one waiting to be
    downloaded, so Settings can pick up where it was when it was closed."""
    latest = metadata_export.latest_export() if settings.app_mode != "app" else None
    return MetadataExportStatus(
        job_id=get_job_runner().get_active_job_id(metadata_export.JOB_NAME),
        latest=latest.name if latest else None,
    )


@router.post("/metadata-export", status_code=202, response_model=MetadataExportStarted)
@limiter.limit(lambda: settings.rate_limit_expensive)
def start_metadata_export(request: Request, body: MetadataExportRequest):
    """Export the library's metadata as a background job. A JSON body, so a page on another
    site can't start one (it would need a CORS preflight, which is refused)."""
    target = _export_target(body.path)
    runner = get_job_runner()
    # Check-and-start is one step, so two clicks can't start two exports, and the hourly
    # clean can't delete the partial files of one being started.
    with metadata_export.export_lock:
        if runner.has_active_job(metadata_export.JOB_NAME):
            raise HTTPException(status_code=409, detail="An export is already running")
        _refuse_while_reembedding(runner)
        metadata_export.clean_exports()
        job_id = runner.submit(
            metadata_export.export_metadata, target, name=metadata_export.JOB_NAME
        )
    return MetadataExportStarted(job_id=job_id)


@router.get("/metadata-export/{name}")
def download_metadata_export(name: str):
    """A finished export in the exports folder, as a download."""
    if not metadata_export.is_export_name(name):
        raise HTTPException(status_code=404, detail="Not Found")
    path = settings.metadata_exports_dir / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="That export has expired; export again")
    return FileResponse(
        path,
        media_type="application/gzip",
        filename=name,
        headers={"X-Accel-Buffering": "no"},
    )


# Full library export (design/export-backup-move.md §7)


def _full_export_target(body: FullExportRequest) -> Path:
    """The desktop app's chosen folder: empty, or an export to carry on. On a server, a new
    folder in its exports folder, or with ``resume`` its newest one."""
    if settings.app_mode != "app":
        if body.path is not None:
            raise HTTPException(
                status_code=422, detail="A folder can only be given in the desktop app"
            )
        latest = export_library.latest_server_export()
        if body.resume and latest is not None:
            return latest
        if latest is not None:
            # One at a time on the library's own disk: each can be as big as the library
            raise HTTPException(
                status_code=409,
                detail=f"There's an export already, in {latest}. Carry it on, or delete it "
                "from the server first.",
            )
        return export_library.server_export_dir()
    if body.path is None:
        raise HTTPException(status_code=422, detail="Choose a folder to export to")
    path = Path(body.path)
    if not path.is_absolute():
        raise HTTPException(status_code=422, detail=f"Not an absolute path: {body.path}")
    _outside_library(path)
    try:
        export_library.check_target(path)
        with pipeline_db() as db:
            export_library.check_export_header(path, get_library_id(db))
    except (ValueError, OSError) as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
    return path


@router.get("/full-export", response_model=FullExportStatus)
def full_export_status():
    """The export running now, and on a server where exports go and the newest one."""
    server = settings.app_mode != "app"
    latest = export_library.latest_server_export() if server else None
    return FullExportStatus(
        job_id=get_job_runner().get_active_job_id(export_library.JOB_NAME),
        folder=str(export_library.server_exports_dir()) if server else "",
        latest=str(latest) if latest else None,
    )


@router.post("/full-export", status_code=202, response_model=FullExportStarted)
@limiter.limit(lambda: settings.rate_limit_expensive)
def start_full_export(request: Request, body: FullExportRequest):
    """Export every image and its metadata as a folder, as a background job (a JSON body:
    see ``start_metadata_export``)."""
    target = _full_export_target(body)
    runner = get_job_runner()
    with metadata_export.export_lock:  # the purge takes it too
        if runner.has_active_job(export_library.JOB_NAME):
            raise HTTPException(status_code=409, detail="An export is already running")
        for job in (PURGE_JOB_NAME, library_rebuild.JOB_NAME):
            if runner.has_active_job(job):  # it deletes or replaces what an export reads
                raise HTTPException(status_code=409, detail=f"{job} is running; try again after")
        _refuse_while_reembedding(runner)
        job_id = runner.submit(
            export_library.export_library,
            target,
            include_linked=body.include_linked,
            name=export_library.JOB_NAME,
        )
    return FullExportStarted(job_id=job_id, path=str(target))


# Move library (design/export-backup-move.md §10): desktop app only


def _desktop_only() -> None:
    if settings.app_mode != "app":
        raise HTTPException(status_code=404, detail="Not Found")


@router.get("/move", response_model=MoveStatus)
def move_status(db: Session = Depends(get_db)):
    _desktop_only()
    return MoveStatus(
        job_id=get_job_runner().get_active_job_id(library_move.JOB_NAME),
        moved_from=library_move.moved_from(db),
    )


@router.post("/move", status_code=202)
@limiter.limit(lambda: settings.rate_limit_expensive)
def start_move(request: Request, body: MoveRequest):
    """Copy the folders to their new places while the app runs. Its result is the new
    folders, which the app then restarts on (Electron's library:apply-move)."""
    _desktop_only()
    runner = get_job_runner()
    with metadata_export.export_lock:
        for job in (library_move.JOB_NAME, PURGE_JOB_NAME, library_rebuild.JOB_NAME):
            if runner.has_active_job(job):
                raise HTTPException(status_code=409, detail=f"{job} is running; try again after")
        try:
            moves = library_move.plan(body.app_data, body.store)
        except library_move.MoveError as e:
            raise HTTPException(status_code=422, detail=str(e)) from None
        job_id = runner.submit(library_move.copy_job, moves, name=library_move.JOB_NAME)
    return {"job_id": job_id}


@router.delete("/move/old")
def delete_old_folders(db: Session = Depends(get_db)):
    """Delete the folders the library was moved from."""
    _desktop_only()
    return {"deleted": library_move.delete_old(db)}
