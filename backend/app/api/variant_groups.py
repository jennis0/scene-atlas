"""Variant groups API endpoints."""

import re
from typing import List, Optional, Set

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func
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
    VariantGroupMergeRequest,
    VariantGroupMergeResponse,
    VariantGroupSearchItem,
    VariantGroupSearchResponse,
)
from ..services import safe_delete_image

router = APIRouter()


def _tokenize(name: str) -> Set[str]:
    """Split a group name into lowercase alphanumeric tokens."""
    return set(re.findall(r"[a-z0-9]+", name.lower()))


def _token_jaccard(a: Set[str], b: Set[str]) -> float:
    """Token Jaccard similarity: |intersection| / |union|."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def get_db(request: Request):
    """Dependency to get database session."""
    SessionLocal = get_session_local(request.app.state.db_engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/search", response_model=VariantGroupSearchResponse)
async def search_variant_groups(
    q: str = "",
    exclude_id: Optional[int] = None,
    limit: int = Query(20, ge=1, le=100),
    reference_name: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Search variant groups by base_name for typeahead picker.

    When reference_name is provided, results are ranked by token Jaccard
    similarity to that name rather than returned alphabetically.
    """
    query = db.query(VariantGroup)

    if q.strip():
        query = query.filter(VariantGroup.base_name.ilike(f"%{q.strip()}%"))

    if exclude_id is not None:
        query = query.filter(VariantGroup.id != exclude_id)

    if reference_name:
        # Fetch all matching rows and rank by similarity in Python.
        # For thousands of groups this is still fast (in-memory sort).
        all_groups = query.order_by(VariantGroup.base_name).all()
        total = len(all_groups)
        ref_tokens = _tokenize(reference_name)
        groups = sorted(
            all_groups,
            key=lambda g: _token_jaccard(ref_tokens, _tokenize(g.base_name)),
            reverse=True,
        )[:limit]
    else:
        total = query.count()
        groups = query.order_by(VariantGroup.base_name).limit(limit).all()

    # Batch-compute image counts
    group_ids = [g.id for g in groups]
    counts = {}
    if group_ids:
        rows = (
            db.query(Image.variant_group_id, func.count(Image.id))
            .filter(Image.variant_group_id.in_(group_ids))
            .group_by(Image.variant_group_id)
            .all()
        )
        counts = {gid: cnt for gid, cnt in rows}

    result = [
        VariantGroupSearchItem(
            id=g.id,
            base_name=g.base_name,
            author=g.author,
            primary_image_id=g.primary_image_id,
            image_count=counts.get(g.id, 0),
        )
        for g in groups
    ]

    return VariantGroupSearchResponse(groups=result, total=total)


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


@router.post("/{group_id}/merge", response_model=VariantGroupMergeResponse)
async def merge_variant_group(
    group_id: int,
    payload: VariantGroupMergeRequest,
    db: Session = Depends(get_db),
):
    """Merge source group into target group.

    Moves all images from source (group_id) into target (payload.target_group_id).
    Updates each image's variant_group_id and author to match the target.
    Deletes the now-empty source group.
    """
    if group_id == payload.target_group_id:
        raise HTTPException(status_code=400, detail="Cannot merge a group into itself")

    source = db.query(VariantGroup).filter(VariantGroup.id == group_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="Source variant group not found")

    target = db.query(VariantGroup).filter(VariantGroup.id == payload.target_group_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Target variant group not found")

    # Move all images from source to target
    images = db.query(Image).filter(Image.variant_group_id == group_id).all()
    for image in images:
        image.variant_group_id = target.id
        image.author = target.author

    images_moved = len(images)

    # Flush so SQLAlchemy's identity map knows the images belong to target,
    # otherwise db.delete(source) will null out their variant_group_id
    # via the back_populates relationship bookkeeping.
    db.flush()

    # Delete the now-empty source group
    db.delete(source)
    db.commit()

    return VariantGroupMergeResponse(
        target_group_id=target.id,
        target_group_name=target.base_name,
        images_moved=images_moved,
        source_group_deleted=True,
    )
