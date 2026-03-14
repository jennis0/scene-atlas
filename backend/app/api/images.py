"""Images API endpoints."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..config import settings
from ..models import (
    Image,
    ImageResponse,
)
from ..services import get_image_store, get_thumbnail_store, safe_delete_image
from .dependencies import get_db
from .rate_limits import limiter

logger = logging.getLogger(__name__)


class ImagePatch(BaseModel):
    name: str | None = None
    subgroup: str | None = None
    gridded: bool | None = None
    grid_width: int | None = None
    grid_height: int | None = None
    grid_type: str | None = None
    image_type: str | None = None


router = APIRouter()


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
    images = db.query(Image).offset(skip).limit(limit).all()
    return images


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
    for field, value in patch.model_dump(exclude_unset=True).items():
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

    scenes = db.query(Image).filter(Image.group_id == image.group_id).all()

    return scenes


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
