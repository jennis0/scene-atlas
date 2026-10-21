"""System information and admin endpoints — storage, library stats, updates, purge."""

import logging
import os
import shutil
from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..config import settings
from ..library_identity import rewrite_markers
from ..models import (
    Color,
    Image,
    ImageGroup,
    ImportGroup,
    ImportItem,
    ImportJob,
    LibrarySource,
    SourceFile,
    Tag,
    TagCategory,
    seed_tag_categories,
)
from ..models.schemas import UpdateCheckResponse
from ..services.update_check import get_update_checker
from ..storage_lock import LOCK_FILENAME
from .dependencies import get_db
from .rate_limits import limiter

logger = logging.getLogger(__name__)
router = APIRouter()


def _dir_size(path: Path) -> int:
    """Recursively sum file sizes under *path*; returns 0 if path doesn't exist."""
    total = 0
    try:
        for entry in os.scandir(path):
            if entry.is_file(follow_symlinks=False):
                total += entry.stat().st_size
            elif entry.is_dir(follow_symlinks=False):
                total += _dir_size(Path(entry.path))
    except (PermissionError, OSError):
        pass
    return total


def _distinct_roots(*roots: Path) -> list[Path]:
    """*roots* without any that lie inside another, so nothing is counted twice: one
    folder for both, or the server default of the library inside the data folder."""
    resolved = list(dict.fromkeys(r.resolve() for r in roots))
    return [r for r in resolved if not any(r != o and r.is_relative_to(o) for o in resolved)]


@router.get("/info")
def system_info(db: Session = Depends(get_db)):
    """Return storage usage and library statistics.

    Intended for the desktop settings panel (app mode).  Also available in
    server mode for diagnostics.
    """
    image_count = db.query(Image).count()
    group_count = db.query(ImageGroup).count()

    images_bytes = _dir_size(settings.store_images_dir)
    thumbnails_bytes = _dir_size(settings.store_thumbnails_dir)
    vector_db_bytes = _dir_size(settings.vector_db_path)
    db_path = settings.app_data_dir / "battlemap.db"
    db_bytes = db_path.stat().st_size if db_path.exists() else 0
    total_bytes = sum(
        _dir_size(root)
        for root in _distinct_roots(settings.app_data_dir, settings.image_library_dir)
    )

    result = {
        "mode": settings.app_mode,
        "storage": {
            "images_bytes": images_bytes + thumbnails_bytes,
            "vectors_bytes": vector_db_bytes,
            "metadata_bytes": db_bytes,
            "total_bytes": total_bytes,
        },
        "library": {
            "image_count": image_count,
            "group_count": group_count,
        },
    }
    # Only expose filesystem paths in desktop mode — avoid leaking
    # internal server structure when running behind a reverse proxy.
    if settings.app_mode == "app":
        result["app_data_path"] = str(settings.app_data_dir)
        result["image_library_path"] = str(settings.image_library_dir)
    return result


@router.get("/updates", response_model=UpdateCheckResponse)
def update_status():
    """Whether a newer release is out, from the server's last daily check (server mode).

    Returns the cached result only: a request never contacts GitHub, so users can't use
    up the server's rate limit. Disabled in the desktop app, which checks for itself.
    """
    return get_update_checker().status()


# Library purge (background job)


def _empty_store(store: Path) -> None:
    """Delete everything in the store except its lock file, which this process holds
    open: Windows can't delete it, and elsewhere a second backend could then lock a new
    one. The library marker goes too, and is written again afterwards."""
    if not store.is_dir():
        return
    for entry in os.scandir(store):
        if entry.name == LOCK_FILENAME:
            continue
        if entry.is_dir(follow_symlinks=False):
            shutil.rmtree(entry.path)
        else:
            os.unlink(entry.path)


def _purge_library(
    db_engine,
    progress_fn: Callable[[int, int, str | None], None] | None = None,
) -> dict:
    """Delete all images, metadata, thumbnails, and vectors.

    Runs as a background job via JobRunner so the API stays responsive
    while potentially gigabytes of files are removed. The linked folder is never
    touched: only its rows go, and its next scan adds its maps again.
    """
    from ..models import get_session_local
    from ..services.lancedb_service import get_lancedb_service

    SessionLocal = get_session_local(db_engine)
    db = SessionLocal()

    steps, current = 6, 0

    def _step(msg: str) -> None:
        nonlocal current
        current += 1
        logger.info("Purge library [%d/%d]: %s", current, steps, msg)
        if progress_fn:
            progress_fn(current, steps, msg)

    try:
        _step("Deleting tags and colors")
        db.query(Tag).delete()
        db.query(Color).delete()
        db.commit()

        _step("Deleting import records")
        db.query(ImportItem).delete()
        db.query(ImportGroup).delete()
        db.query(ImportJob).delete()
        db.query(SourceFile).delete()
        db.query(LibrarySource).delete()
        db.commit()

        _step("Deleting images and groups")
        db.query(Image).delete()
        db.query(ImageGroup).delete()
        db.commit()

        _step("Removing image files")
        _empty_store(settings.store_images_dir)
        rewrite_markers(db)

        _step("Removing thumbnail files")
        if settings.store_thumbnails_dir.exists():
            shutil.rmtree(settings.store_thumbnails_dir)
            settings.store_thumbnails_dir.mkdir(parents=True, exist_ok=True)

        _step("Resetting vector index")
        svc = get_lancedb_service()
        svc.delete_collection()
        svc.ensure_collection()

        return {"message": "Library purged successfully"}
    finally:
        db.close()


@router.delete("/library")
@limiter.limit(lambda: settings.rate_limit_destructive)
def delete_library(request: Request, db: Session = Depends(get_db)):
    """Purge the entire library (images, metadata, vectors, files).

    Submits a background job and returns immediately with a job ID.
    Refuses to run if any import jobs are currently active.
    """
    from ...pipeline.linked_scanner import get_linked_scanner
    from ..services.job_runner import PURGE_JOB_NAME, get_job_runner

    runner = get_job_runner()
    if runner.has_active_job(PURGE_JOB_NAME):
        raise HTTPException(status_code=409, detail="Library purge already in progress")
    if get_linked_scanner().running:
        raise HTTPException(
            status_code=409, detail="Your maps folder is being checked; try again in a moment"
        )

    active_imports = (
        db.query(ImportItem.job_id)
        .filter(ImportItem.state.in_(("awaiting_bytes", "ready", "processing")))
        .distinct()
        .count()
    )
    if active_imports:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot purge library while {active_imports} import(s) are in progress. "
            "Cancel or wait for them to finish first.",
        )

    job_id = runner.submit(
        _purge_library,
        request.app.state.db_engine,
        name=PURGE_JOB_NAME,
    )
    return {"job_id": job_id, "message": "Library purge started"}


# Tag reset (synchronous)


@router.post("/tags/reset")
@limiter.limit(lambda: settings.rate_limit_destructive)
def reset_tags(request: Request, db: Session = Depends(get_db)):
    """Delete all per-image tags and tag categories, then re-seed defaults.

    This is a fast DB-only operation (no files or vectors affected).
    """
    deleted_tags = db.query(Tag).delete()
    deleted_categories = db.query(TagCategory).delete()
    db.commit()

    seed_tag_categories(db)
    db.commit()

    seeded_categories = db.query(TagCategory).count()

    return {
        "deleted_tags": deleted_tags,
        "deleted_categories": deleted_categories,
        "seeded_categories": seeded_categories,
    }
