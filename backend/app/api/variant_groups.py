"""Variant groups API endpoints."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session, joinedload

from ..models import (
    Image,
    Tag,
    VariantGroup,
    get_session_local,
)
from ..models.schemas import (
    VariantGroupDetailResponse,
    VariantGroupEditRequest,
    VariantGroupEditResponse,
)
from ..services import safe_delete_image

router = APIRouter()


def get_db(request: Request):
    """Dependency to get database session."""
    SessionLocal = get_session_local(request.app.state.db_engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/{group_id}", response_model=VariantGroupDetailResponse)
async def get_variant_group(
    group_id: int,
    db: Session = Depends(get_db),
):
    """Get a variant group with all its images."""
    group = (
        db.query(VariantGroup)
        .options(
            joinedload(VariantGroup.images).joinedload(Image.tags),
            joinedload(VariantGroup.images).joinedload(Image.colors),
        )
        .filter(VariantGroup.id == group_id)
        .first()
    )
    if not group:
        raise HTTPException(status_code=404, detail="Variant group not found")
    return group


@router.put("/{group_id}", response_model=VariantGroupEditResponse)
async def edit_variant_group(
    group_id: int,
    payload: VariantGroupEditRequest,
    db: Session = Depends(get_db),
):
    """Edit a variant group: update metadata, delete images, update images, split off new groups."""
    group = db.query(VariantGroup).filter(VariantGroup.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Variant group not found")

    # 1. Update group-level metadata
    group.base_name = payload.base_name
    group.author = payload.author

    # 2. Determine which images to keep
    kept_ids = {img.id for img in payload.images}
    all_images = db.query(Image).filter(Image.variant_group_id == group_id).all()

    deleted_ids: List[int] = []
    for image in all_images:
        if image.id not in kept_ids:
            deleted_ids.append(image.id)
            safe_delete_image(db, image)

    # 3. Update kept images
    image_map = {img.id: img for img in all_images if img.id in kept_ids}
    for img_payload in payload.images:
        image = image_map.get(img_payload.id)
        if not image:
            continue
        image.name = img_payload.name
        image.author = payload.author  # sync author to group
        image.gridded = img_payload.gridded
        image.grid_width = img_payload.grid_width
        image.grid_height = img_payload.grid_height
        image.sub_variant = img_payload.sub_variant
        # Replace tags
        for tag in list(image.tags):
            db.delete(tag)
        db.flush()
        for tag_data in img_payload.tags:
            db.add(
                Tag(
                    image_id=image.id,
                    category=tag_data.category,
                    value=tag_data.value,
                    confidence=tag_data.confidence,
                    source=tag_data.source,
                )
            )

    # 4. Fix primary_image_id if deleted
    if group.primary_image_id and group.primary_image_id not in kept_ids:
        remaining = [img for img in all_images if img.id in kept_ids]
        group.primary_image_id = remaining[0].id if remaining else None

    # 5. Create split-off groups
    new_group_ids: List[int] = []
    for new_group_payload in payload.new_groups:
        new_group = VariantGroup(
            base_name=new_group_payload.base_name,
            author=new_group_payload.author,
        )
        db.add(new_group)
        db.flush()  # get new_group.id
        for img_id in new_group_payload.image_ids:
            image = db.query(Image).filter(Image.id == img_id).first()
            if image:
                image.variant_group_id = new_group.id
                image.author = new_group_payload.author
        new_group.primary_image_id = (
            new_group_payload.image_ids[0] if new_group_payload.image_ids else None
        )
        new_group_ids.append(new_group.id)

    db.commit()
    return VariantGroupEditResponse(
        id=group_id,
        new_group_ids=new_group_ids,
        deleted_image_ids=deleted_ids,
    )


@router.delete("/{group_id}")
async def delete_variant_group(
    group_id: int,
    db: Session = Depends(get_db),
):
    """Delete a variant group and all its images."""
    group = db.query(VariantGroup).filter(VariantGroup.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Variant group not found")

    images = db.query(Image).filter(Image.variant_group_id == group_id).all()
    for image in images:
        safe_delete_image(db, image)

    db.delete(group)
    db.commit()
    return {"message": f"Variant group {group_id} and all its images deleted"}
