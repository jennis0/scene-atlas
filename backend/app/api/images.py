"""Images API endpoints."""

import logging
import mimetypes
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload, selectinload

from ..config import settings
from ..models import (
    Image,
    ImageResponse,
)
from ..models.database import GRID_FIELDS, GRID_SOURCE_USER
from ..models.schemas import (
    BulkImageEditRequest,
    BulkImageEditResponse,
    BulkImageRestoreRequest,
    BulkImageRestoreResponse,
)
from ..services import get_image_store, get_thumbnail_store, safe_delete_image
from ..services.bulk_edit_service import bulk_edit_images, restore_images
from .dependencies import get_db, write_locked
from .rate_limits import limiter

logger = logging.getLogger(__name__)

# FileResponse guesses Content-Type from the extension. Python < 3.13 only knows
# .webp when the OS registry / mime.types does, otherwise it serves
# application/octet-stream. WebP is used for transparent thumbnails and for
# originals stored as WebP.
mimetypes.add_type("image/webp", ".webp")


class ImagePatch(BaseModel):
    name: str | None = None
    subgroup: str | None = None
    gridded: bool | None = None
    grid_width: int | None = None
    grid_height: int | None = None
    grid_type: str | None = None
    image_type: Literal["battlemap", "scene"] | None = None


router = APIRouter()

# ImageResponse includes tags, colours and the group name; without eager loading
# each listed image costs three more queries.
_WITH_RELATIONS = (selectinload(Image.tags), selectinload(Image.colors), joinedload(Image.group))


@router.get("/authors", response_model=list[str])
def list_authors(db: Session = Depends(get_db)):
    """List all distinct non-empty author values."""
    rows = (
        db.query(Image.author).filter(Image.author.isnot(None), Image.author != "").distinct().all()
    )
    return sorted([r[0] for r in rows])


@router.get("/", response_model=list[ImageResponse])
def list_images(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """List all images with pagination."""
    return db.query(Image).options(*_WITH_RELATIONS).offset(skip).limit(limit).all()


@router.post("/bulk-edit", response_model=BulkImageEditResponse)
@write_locked
def bulk_edit(request: BulkImageEditRequest, db: Session = Depends(get_db)):
    """Apply one change (fields and/or tags to add) to many images in one transaction.

    Returns the images' previous state for ``/bulk-restore`` (undo). Unknown ids are skipped.
    """
    previous, added_tag_ids = bulk_edit_images(
        db,
        request.image_ids,
        request.changes.model_dump(exclude_unset=True),
        request.add_tags,
    )
    db.commit()
    return BulkImageEditResponse(
        updated=len(previous), previous=previous, added_tag_ids=added_tag_ids
    )


@router.post("/bulk-restore", response_model=BulkImageRestoreResponse)
@write_locked
def bulk_restore(request: BulkImageRestoreRequest, db: Session = Depends(get_db)):
    """Undo a bulk edit: put back the states it returned and drop the tags it added."""
    restored = restore_images(db, request.images, request.remove_tag_ids)
    db.commit()
    return BulkImageRestoreResponse(restored=restored)


@router.get("/{image_id}", response_model=ImageResponse)
def get_image(image_id: int, db: Session = Depends(get_db)):
    """Get a specific image by ID."""
    image = db.query(Image).filter(Image.id == image_id).first()
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")
    return image


@router.patch("/{image_id}", response_model=ImageResponse)
def patch_image(image_id: int, patch: ImagePatch, db: Session = Depends(get_db)):
    """Update image metadata (name, subgroup, gridded, grid dimensions)."""
    image = db.query(Image).filter(Image.id == image_id).first()
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")
    updates = patch.model_dump(exclude_unset=True)

    # When gridded is explicitly set to False, clear grid fields unless
    # they are explicitly included in the patch payload.
    if updates.get("gridded") is False:
        for grid_field in ("grid_width", "grid_height", "grid_type"):
            if grid_field not in updates:
                updates[grid_field] = None

    if any(f in updates and updates[f] != getattr(image, f) for f in GRID_FIELDS):
        image.grid_source = GRID_SOURCE_USER
        image.grid_confidence = None
    for field, value in updates.items():
        setattr(image, field, value)
    db.commit()
    db.refresh(image)
    return image


@router.delete("/{image_id}")
def delete_image(image_id: int, db: Session = Depends(get_db)):
    """Delete an image and its files from stores (ref-counted)."""
    image = db.query(Image).filter(Image.id == image_id).first()
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")

    safe_delete_image(db, image)
    db.commit()
    return {"message": "Image deleted successfully"}


@router.get("/{image_id}/scenes", response_model=list[ImageResponse])
def get_image_scenes(image_id: int, db: Session = Depends(get_db)):
    """Get all scenes in the same group as this image."""
    image = db.query(Image).filter(Image.id == image_id).first()
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")

    if not image.group_id:
        return [image]  # No group, return just this image

    return db.query(Image).options(*_WITH_RELATIONS).filter(Image.group_id == image.group_id).all()


@router.get("/{image_id}/file")
def get_image_file(image_id: int, db: Session = Depends(get_db)):
    """Serve the original image file via ImageStore."""
    image = db.query(Image).filter(Image.id == image_id).first()
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")

    image_store = get_image_store()
    file_path = image_store.get_path(image.storage_key)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Image file not found")

    return FileResponse(file_path)


@router.get("/{image_id}/thumbnail")
def get_image_thumbnail(image_id: int, db: Session = Depends(get_db)):
    """Serve the image thumbnail via ImageStore."""
    image = db.query(Image).filter(Image.id == image_id).first()
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")

    # Use thumbnail if available
    if image.thumbnail_key:
        thumbnail_store = get_thumbnail_store()
        thumbnail_path = thumbnail_store.get_path(image.thumbnail_key)
        if thumbnail_path.exists():
            return FileResponse(thumbnail_path)

    # Fallback to original image — thumbnail missing or not yet generated
    logger.warning(
        "Thumbnail not found for image %d (key=%s), falling back to full-resolution",
        image_id,
        image.thumbnail_key,
    )
    image_store = get_image_store()
    file_path = image_store.get_path(image.storage_key)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Image file not found")

    return FileResponse(file_path)


# ── Bulk Grid Detection ──────────────────────────────────────────────────────


@router.post("/backfill-grids")
@limiter.limit(lambda: settings.rate_limit_expensive)
def trigger_backfill_grids(request: Request, force: bool = False):
    """Run grid detection on battlemaps missing grid info (background job).

    Pass ?force=true to re-detect ALL battlemaps.
    """
    from ...pipeline.backfill_grid_detection import backfill_grid_detection
    from ..services.job_runner import get_job_runner

    try:
        runner = get_job_runner()
        if runner.has_active_job("Backfill grid detection"):
            raise HTTPException(
                status_code=409, detail="Grid detection backfill already in progress"
            )
        job_id = runner.submit(backfill_grid_detection, force=force, name="Backfill grid detection")
        return {"job_id": job_id, "message": "Grid detection backfill started"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=503, detail=f"Could not start grid backfill job: {e}"
        ) from e
