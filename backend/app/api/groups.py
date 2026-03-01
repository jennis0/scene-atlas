"""Groups API endpoints."""

import re

import zipstream
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from ...pipeline.naming import download_filename, sanitize_segment
from ..models import (
    Image,
    ImageGroup,
    Tag,
)
from ..models.schemas import (
    ConfirmReviewRequest,
    GroupDetailResponse,
    GroupEditRequest,
    GroupEditResponse,
    GroupMergeRequest,
    GroupMergeResponse,
    GroupSearchItem,
    GroupSearchResponse,
    MoveImagesRequest,
    MoveImagesResponse,
)
from ..services import get_image_store, safe_delete_image
from .dependencies import get_db

router = APIRouter()


def _tokenize(name: str) -> set[str]:
    """Split a group name into lowercase alphanumeric tokens."""
    return set(re.findall(r"[a-z0-9]+", name.lower()))


def _token_jaccard(a: set[str], b: set[str]) -> float:
    """Token Jaccard similarity: |intersection| / |union|."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _zip_path(img: Image, group_name: str) -> str:
    """Return the archive path for an image: group[/subgroup]/filename."""
    folder = sanitize_segment(group_name)
    if img.subgroup:
        folder = f"{folder}/{sanitize_segment(img.subgroup)}"
    return f"{folder}/{download_filename(img, group_name)}"


@router.get("/search", response_model=GroupSearchResponse)
async def search_groups(
    q: str = "",
    exclude_id: int | None = None,
    limit: int = Query(20, ge=1, le=100),
    reference_name: str | None = None,
    db: Session = Depends(get_db),
):
    """Search groups by base_name for typeahead picker.

    When reference_name is provided, results are ranked by token Jaccard
    similarity to that name rather than returned alphabetically.
    """
    query = db.query(ImageGroup)

    if q.strip():
        escaped = re.sub(r"([%_\\])", r"\\\1", q.strip())
        query = query.filter(ImageGroup.base_name.ilike(f"%{escaped}%"))

    if exclude_id is not None:
        query = query.filter(ImageGroup.id != exclude_id)

    if reference_name:
        # Fetch all matching rows and rank by similarity in Python.
        # For thousands of groups this is still fast (in-memory sort).
        all_groups = query.order_by(ImageGroup.base_name).all()
        total = len(all_groups)
        ref_tokens = _tokenize(reference_name)
        groups = sorted(
            all_groups,
            key=lambda g: _token_jaccard(ref_tokens, _tokenize(g.base_name)),
            reverse=True,
        )[:limit]
    else:
        total = query.count()
        groups = query.order_by(ImageGroup.base_name).limit(limit).all()

    # Batch-compute image counts
    group_ids = [g.id for g in groups]
    counts = {}
    if group_ids:
        rows = (
            db.query(Image.group_id, func.count(Image.id))
            .filter(Image.group_id.in_(group_ids))
            .group_by(Image.group_id)
            .all()
        )
        counts = dict(rows)

    result = [
        GroupSearchItem(
            id=g.id,
            base_name=g.base_name,
            author=g.author,
            primary_image_id=g.primary_image_id,
            image_count=counts.get(g.id, 0),
        )
        for g in groups
    ]

    return GroupSearchResponse(groups=result, total=total)


@router.get("/{group_id}", response_model=GroupDetailResponse)
async def get_group(
    group_id: int,
    db: Session = Depends(get_db),
):
    """Get a group with all its images."""
    group = (
        db.query(ImageGroup)
        .options(
            joinedload(ImageGroup.images).joinedload(Image.tags),
            joinedload(ImageGroup.images).joinedload(Image.colors),
        )
        .filter(ImageGroup.id == group_id)
        .first()
    )
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    return group


@router.get("/{group_id}/download")
async def download_group(
    group_id: int,
    db: Session = Depends(get_db),
):
    """Download all images in a group as a ZIP archive.

    ZIP structure:
        {group_name}/
            {subgroup}/         ← only when the image has a subgroup
                {filename}
            {filename}          ← images without a subgroup sit directly in group folder
    """
    group = db.query(ImageGroup).filter(ImageGroup.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    images = db.query(Image).filter(Image.group_id == group_id).all()
    image_store = get_image_store()

    zs = zipstream.ZipStream(compress_type=zipstream.ZIP_STORED, sized=True)
    for img in images:
        file_path = image_store.get_path(img.storage_key)
        if file_path and file_path.exists():
            zs.add_path(file_path, arcname=_zip_path(img, group.base_name))

    zip_name = sanitize_segment(group.base_name) + ".zip"
    return StreamingResponse(
        zs,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{zip_name}"',
            "Content-Length": str(len(zs)),
        },
    )


@router.put("/{group_id}", response_model=GroupEditResponse)
async def edit_group(
    group_id: int,
    payload: GroupEditRequest,
    db: Session = Depends(get_db),
):
    """Edit a group: update metadata, delete images, update images, split off new groups."""
    group = db.query(ImageGroup).filter(ImageGroup.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    # 1. Update group-level metadata
    group.base_name = payload.base_name
    group.author = payload.author

    # 2. Determine which images to keep vs delete.
    # Images referenced in new_groups are being moved, not deleted — protect them.
    kept_ids = {img.id for img in payload.images}
    moving_ids = {img_id for ng in payload.new_groups for img_id in ng.image_ids}
    all_images = db.query(Image).filter(Image.group_id == group_id).all()

    deleted_ids: list[int] = []
    for image in all_images:
        if image.id not in kept_ids and image.id not in moving_ids:
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
        image.grid_type = img_payload.grid_type
        image.subgroup = img_payload.subgroup
        if img_payload.image_type is not None:
            image.image_type = img_payload.image_type
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
    new_group_ids: list[int] = []
    for new_group_payload in payload.new_groups:
        new_group = ImageGroup(
            base_name=new_group_payload.base_name,
            author=new_group_payload.author,
        )
        db.add(new_group)
        db.flush()  # get new_group.id
        for img_id in new_group_payload.image_ids:
            image = db.query(Image).filter(Image.id == img_id).first()
            if image:
                image.group_id = new_group.id
                image.author = new_group_payload.author
        new_group.primary_image_id = (
            new_group_payload.image_ids[0] if new_group_payload.image_ids else None
        )
        new_group_ids.append(new_group.id)

    db.commit()
    return GroupEditResponse(
        id=group_id,
        new_group_ids=new_group_ids,
        deleted_image_ids=deleted_ids,
    )


@router.delete("/{group_id}")
async def delete_group(
    group_id: int,
    db: Session = Depends(get_db),
):
    """Delete a group and all its images."""
    group = db.query(ImageGroup).filter(ImageGroup.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    images = db.query(Image).filter(Image.group_id == group_id).all()
    for image in images:
        safe_delete_image(db, image)

    db.delete(group)
    db.commit()
    return {"message": f"Group {group_id} and all its images deleted"}


@router.post("/{group_id}/move-images", response_model=MoveImagesResponse)
async def move_images(
    group_id: int,
    payload: MoveImagesRequest,
    db: Session = Depends(get_db),
):
    """Move specific images from source group to target group.

    Unlike merge, this moves only the listed images and keeps the source group
    alive (unless it becomes empty, in which case it is auto-deleted).
    """
    if group_id == payload.target_group_id:
        raise HTTPException(status_code=400, detail="Source and target group are the same")

    source = db.query(ImageGroup).filter(ImageGroup.id == group_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="Source group not found")

    target = db.query(ImageGroup).filter(ImageGroup.id == payload.target_group_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Target group not found")

    # Validate all image_ids belong to source group
    images = (
        db.query(Image).filter(Image.id.in_(payload.image_ids), Image.group_id == group_id).all()
    )
    if len(images) != len(payload.image_ids):
        found_ids = {img.id for img in images}
        missing = [i for i in payload.image_ids if i not in found_ids]
        raise HTTPException(
            status_code=400,
            detail=f"Images not found in source group: {missing}",
        )

    # Move images to target
    for image in images:
        image.group_id = target.id
        image.author = target.author

    images_moved = len(images)

    # Fix primary_image_id on source if it was moved
    if source.primary_image_id and source.primary_image_id in {img.id for img in images}:
        remaining = (
            db.query(Image)
            .filter(Image.group_id == group_id, Image.id.notin_(payload.image_ids))
            .first()
        )
        source.primary_image_id = remaining.id if remaining else None

    db.flush()

    # Auto-delete source if now empty
    remaining_count = db.query(func.count(Image.id)).filter(Image.group_id == group_id).scalar()
    source_deleted = remaining_count == 0
    if source_deleted:
        db.delete(source)

    db.commit()

    return MoveImagesResponse(
        source_group_id=group_id,
        target_group_id=target.id,
        images_moved=images_moved,
        source_group_deleted=source_deleted,
    )


@router.post("/{group_id}/merge", response_model=GroupMergeResponse)
async def merge_group(
    group_id: int,
    payload: GroupMergeRequest,
    db: Session = Depends(get_db),
):
    """Merge source group into target group.

    Moves all images from source (group_id) into target (payload.target_group_id).
    Updates each image's group_id and author to match the target.
    Deletes the now-empty source group.
    """
    if group_id == payload.target_group_id:
        raise HTTPException(status_code=400, detail="Cannot merge a group into itself")

    source = db.query(ImageGroup).filter(ImageGroup.id == group_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="Source group not found")

    target = db.query(ImageGroup).filter(ImageGroup.id == payload.target_group_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Target group not found")

    # Move all images from source to target
    images = db.query(Image).filter(Image.group_id == group_id).all()
    for image in images:
        image.group_id = target.id
        image.author = target.author

    images_moved = len(images)

    # Flush so SQLAlchemy's identity map knows the images belong to target,
    # otherwise db.delete(source) will null out their group_id
    # via the back_populates relationship bookkeeping.
    db.flush()

    # Delete the now-empty source group
    db.delete(source)
    db.commit()

    return GroupMergeResponse(
        target_group_id=target.id,
        target_group_name=target.base_name,
        images_moved=images_moved,
        source_group_deleted=True,
    )


@router.post("/confirm-review")
async def confirm_review(
    payload: ConfirmReviewRequest,
    db: Session = Depends(get_db),
):
    """Clear needs_review on all images in the specified groups.

    Called after the user reviews and confirms an import via EditGroupDialog.
    Once cleared, images become visible in gallery search results.
    """
    if not payload.group_ids:
        return {"updated": 0}

    images = (
        db.query(Image)
        .filter(Image.group_id.in_(payload.group_ids), Image.needs_review.is_(True))
        .all()
    )
    for image in images:
        image.needs_review = False
    db.commit()
    return {"updated": len(images)}
