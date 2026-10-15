"""System information and admin endpoints — storage, library stats, purge."""

import logging
import os
import shutil
from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..config import settings
from ..models import (
    Color,
    Image,
    ImageGroup,
    ImportGroup,
    ImportItem,
    ImportJob,
    Tag,
    TagCategory,
    seed_tag_categories,
)
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
    total_bytes = _dir_size(settings.app_data_dir) + _dir_size(settings.image_library_dir)

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


# ── Library purge (background job) ────────────────────────────────────────────


def _purge_library(
    db_engine,
    progress_fn: Callable[[int, int, str | None], None] | None = None,
) -> dict:
    """Delete all images, metadata, thumbnails, and vectors.

    Runs as a background job via JobRunner so the API stays responsive
    while potentially gigabytes of files are removed.
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
        db.commit()

        _step("Deleting images and groups")
        db.query(Image).delete()
        db.query(ImageGroup).delete()
        db.commit()

        _step("Removing image files")
        if settings.store_images_dir.exists():
            shutil.rmtree(settings.store_images_dir)
            settings.store_images_dir.mkdir(parents=True, exist_ok=True)

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
    from ..services.job_runner import get_job_runner

    runner = get_job_runner()
    if runner.has_active_job("Purge library"):
        raise HTTPException(status_code=409, detail="Library purge already in progress")

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
        name="Purge library",
    )
    return {"job_id": job_id, "message": "Library purge started"}


# ── Tag reset (synchronous) ──────────────────────────────────────────────────


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
