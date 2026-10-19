"""Library identity and the linked folder (design/library-setup.md)."""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..config import settings
from ..library_identity import get_library_id, inspect_folders
from ..models.schemas import (
    InspectHints,
    InspectLibrary,
    InspectLinked,
    InspectRequest,
    InspectResult,
    LibraryStatus,
    LinkedLibraryStatus,
)
from .dependencies import acquire_heavy_op, get_db

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
    """The library's ID and its linked folder, if one is configured."""
    library_id = get_library_id(db)
    if library_id is None:  # set at startup, so only a database swapped underneath us
        raise HTTPException(status_code=503, detail="The library isn't open")
    linked = settings.linked_library_dir
    # Until linked scanning exists, the folder's state is whether it's there.
    return LibraryStatus(
        library_id=library_id,
        linked=LinkedLibraryStatus(
            state="online" if linked.is_dir() else "offline",
            name=linked.name,
            path=str(linked) if settings.app_mode == "app" else None,
            image_count=0,
            missing_count=0,
            last_scan_at=None,
            scanning=False,
        )
        if linked is not None
        else None,
    )
