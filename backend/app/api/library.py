"""Library identity and the linked folder (design/library-setup.md)."""

from datetime import UTC
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ...pipeline import ingest_queue as q
from ...pipeline.ingest_worker import get_ingest_worker
from ...pipeline.linked_scan import get_linked_scanner
from ..config import settings
from ..library_identity import get_library_id, inspect_folders
from ..models import LibrarySource
from ..models.database import SOURCE_DETACHED, SOURCE_OFFLINE, SOURCE_ONLINE
from ..models.schemas import (
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
)
from ..services.app_settings import get_settings as get_app_settings
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
    """409 unless a linked folder is configured and in use (not detached by "Stop using
    this folder" while the configuration still names it)."""
    source = current_source(db)
    if settings.linked_library_dir is None or (
        source is not None and source.state == SOURCE_DETACHED
    ):
        raise HTTPException(status_code=409, detail="No images folder is linked")


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
    """Stop using the linked folder: remove every map read from it and forget its files.
    The folder itself is never touched. The source is detached until the configuration
    drops the folder (the desktop app restarts; on a server, unset ``LINKED_LIBRARY_DIR``).
    """
    source = current_source(db)
    if source is None:
        return LinkedRemoved(removed=0)
    if get_linked_scanner().running:
        raise HTTPException(status_code=409, detail="Your images folder is being checked; try again")
    for job in open_linked_jobs(db, source.id):
        q.cancel_job(db, job.id)
    if linked_jobs_busy(db, source.id):
        db.commit()  # keep the cancellation; the batch in progress finishes shortly
        get_ingest_worker().bump()
        raise HTTPException(
            status_code=409, detail="Finishing the current batch; try again in a moment"
        )
    return LinkedRemoved(removed=_remove(db, linked_image_ids(db, source.id), detach=source))
