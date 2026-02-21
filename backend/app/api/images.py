"""Images API endpoints."""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..models import (
    Image,
    ImageResponse,
    get_session_local,
)
from ..services import get_image_store, get_thumbnail_store, safe_delete_image


class ImagePatch(BaseModel):
    name: Optional[str] = None
    sub_variant: Optional[str] = None
    gridded: Optional[bool] = None
    grid_width: Optional[int] = None
    grid_height: Optional[int] = None


router = APIRouter()


def get_db(request: Request):
    """Dependency to get database session."""
    SessionLocal = get_session_local(request.app.state.db_engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/authors", response_model=List[str])
async def list_authors(db: Session = Depends(get_db)):
    """List all distinct non-empty author values."""
    rows = (
        db.query(Image.author).filter(Image.author.isnot(None), Image.author != "").distinct().all()
    )
    return sorted([r[0] for r in rows])


@router.get("/", response_model=List[ImageResponse])
async def list_images(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """List all images with pagination."""
    images = db.query(Image).offset(skip).limit(limit).all()
    return images


@router.get("/{image_id}", response_model=ImageResponse)
async def get_image(image_id: int, db: Session = Depends(get_db)):
    """Get a specific image by ID."""
    image = db.query(Image).filter(Image.id == image_id).first()
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")
    return image


@router.patch("/{image_id}", response_model=ImageResponse)
async def patch_image(image_id: int, patch: ImagePatch, db: Session = Depends(get_db)):
    """Update image metadata (name, sub_variant, gridded, grid dimensions)."""
    image = db.query(Image).filter(Image.id == image_id).first()
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")
    for field, value in patch.model_dump(exclude_unset=True).items():
        setattr(image, field, value)
    db.commit()
    db.refresh(image)
    return image


@router.delete("/{image_id}")
async def delete_image(image_id: int, db: Session = Depends(get_db)):
    """Delete an image and its files from stores (ref-counted)."""
    image = db.query(Image).filter(Image.id == image_id).first()
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")

    safe_delete_image(db, image)
    db.commit()
    return {"message": "Image deleted successfully"}


@router.get("/{image_id}/variants", response_model=List[ImageResponse])
async def get_image_variants(image_id: int, db: Session = Depends(get_db)):
    """Get all variants of an image (images in the same variant group)."""
    image = db.query(Image).filter(Image.id == image_id).first()
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")

    if not image.variant_group_id:
        return [image]  # No variant group, return just this image

    variants = db.query(Image).filter(Image.variant_group_id == image.variant_group_id).all()

    return variants


@router.get("/{image_id}/file")
async def get_image_file(image_id: int, db: Session = Depends(get_db)):
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
async def get_image_thumbnail(image_id: int, db: Session = Depends(get_db)):
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

    # Fallback to original image
    image_store = get_image_store()
    file_path = image_store.get_path(image.storage_key)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Image file not found")

    return FileResponse(file_path)
