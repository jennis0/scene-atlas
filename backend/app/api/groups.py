"""Groups API endpoints."""

import re

import zipstream
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, func
from sqlalchemy.orm import Session, selectinload

from ...pipeline.naming import download_filename, sanitize_segment
from ..models import (
    Image,
    ImageGroup,
    Tag,
)
from ..models.database import GRID_FIELDS, GRID_SOURCE_USER
from ..models.schemas import (
    GroupBulkUpdateRequest,
    GroupBulkUpdateResponse,
    GroupDetailResponse,
    GroupDetailsRequest,
    GroupEditRequest,
    GroupEditResponse,
    GroupMergeRequest,
    GroupMergeResponse,
    GroupPickerItem,
    GroupPickerResponse,
    GroupSummariesRequest,
    GroupSummary,
    MoveImagesRequest,
    MoveImagesResponse,
)
from ..services import get_image_store
from ..services.bulk_edit_service import set_groups_author
from ..services.deletion_service import delete_image_rows
from .dependencies import get_db, write_locked

router = APIRouter()

# A group's images with their tags and colours, as group detail responses carry them.
# Separate SELECTs: joining both collections returns tags x colours rows per image.
_WITH_IMAGE_DETAILS = (
    selectinload(ImageGroup.images).selectinload(Image.tags),
    selectinload(ImageGroup.images).selectinload(Image.colors),
)


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


@router.get("/search", response_model=GroupPickerResponse)
def search_groups(
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
            .tuples()
            .all()
        )
        counts = dict(rows)

    # Compute fallback primary_image_id for groups that don't have one set
    primary_ids: dict[int | None, int] = {}
    missing = [g.id for g in groups if g.primary_image_id is None]
    if missing:
        rows = (
            db.query(Image.group_id, func.min(Image.id))
            .filter(Image.group_id.in_(missing))
            .group_by(Image.group_id)
            .tuples()
            .all()
        )
        primary_ids = dict(rows)

    result = [
        GroupPickerItem(
            id=g.id,
            base_name=g.base_name,
            author=g.author,
            primary_image_id=g.primary_image_id or primary_ids.get(g.id),
            image_count=counts.get(g.id, 0),
        )
        for g in groups
    ]

    return GroupPickerResponse(groups=result, total=total)


def _in_request_order[T: (ImageGroup, GroupSummary)](rows: list[T], ids: list[int]) -> list[T]:
    """Rows in the order their ids were asked for; unknown ids are left out."""
    by_id = {row.id: row for row in rows}
    return [by_id[i] for i in dict.fromkeys(ids) if i in by_id]


@router.post("/summaries", response_model=list[GroupSummary])
def get_group_summaries(
    request: GroupSummariesRequest,
    db: Session = Depends(get_db),
):
    """Many groups at once, without image details: names, counts and image ids.

    POST because the editor asks for thousands of ids at a time. Groups that no longer
    exist are left out, so the client can tell what was merged or deleted meanwhile.
    """
    groups = db.query(ImageGroup).filter(ImageGroup.id.in_(request.ids)).all()
    image_ids: dict[int, list[int]] = {g.id: [] for g in groups}
    rows = (
        db.query(Image.group_id, Image.id)
        .filter(Image.group_id.in_(request.ids))
        .order_by(Image.id)
        .all()
    )
    for group_id, image_id in rows:
        image_ids[group_id].append(image_id)
    summaries = [
        GroupSummary(
            id=g.id,
            base_name=g.base_name,
            author=g.author,
            primary_image_id=g.primary_image_id,
            image_count=g.image_count,
            image_ids=image_ids[g.id],
        )
        for g in groups
    ]
    return _in_request_order(summaries, request.ids)


@router.post("/details", response_model=list[GroupDetailResponse])
def get_group_details(
    request: GroupDetailsRequest,
    db: Session = Depends(get_db),
):
    """Several groups with all their images, in one round trip. Missing groups are left out."""
    groups = (
        db.query(ImageGroup)
        .options(*_WITH_IMAGE_DETAILS)
        .filter(ImageGroup.id.in_(request.ids))
        .all()
    )
    return _in_request_order(groups, request.ids)


@router.post("/bulk-update", response_model=GroupBulkUpdateResponse)
@write_locked
def bulk_update_groups(request: GroupBulkUpdateRequest, db: Session = Depends(get_db)):
    """Set many groups' author in one transaction, instead of a ``PUT`` per group.

    Their images take the author too, as ``PUT /groups/{id}`` does. Unknown ids are skipped.
    """
    updated = set_groups_author(db, request.ids, request.author)
    db.commit()
    return GroupBulkUpdateResponse(updated=updated)


@router.get("/{group_id}", response_model=GroupDetailResponse)
def get_group(
    group_id: int,
    db: Session = Depends(get_db),
):
    """Get a group with all its images."""
    group = (
        db.query(ImageGroup).options(*_WITH_IMAGE_DETAILS).filter(ImageGroup.id == group_id).first()
    )
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    return group


@router.get("/{group_id}/download")
def download_group(
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
@write_locked
def edit_group(
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
    all_images = (
        db.query(Image).options(selectinload(Image.tags)).filter(Image.group_id == group_id).all()
    )

    deleted = [img for img in all_images if img.id not in kept_ids and img.id not in moving_ids]
    deleted_ids = [img.id for img in deleted]
    pending = delete_image_rows(db, deleted)

    # 3. Update kept images
    image_map = {img.id: img for img in all_images if img.id in kept_ids}
    for img_payload in payload.images:
        image = image_map.get(img_payload.id)
        if not image:
            continue
        image.name = img_payload.name
        image.author = payload.author  # sync author to group
        new_grid = {f: getattr(img_payload, f) for f in GRID_FIELDS}
        if any(getattr(image, f) != v for f, v in new_grid.items()):
            for f, v in new_grid.items():
                setattr(image, f, v)
            image.grid_source = GRID_SOURCE_USER
            image.grid_confidence = None
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
        db.flush()  # persist new tags so image.tags reflects them
        db.expire(image)  # clear stale .tags cache before rebuilding search_text
        from ..services.fts_service import rebuild_search_text

        rebuild_search_text(image, db)

    # 4. Fix primary_image_id if deleted
    if group.primary_image_id and group.primary_image_id not in kept_ids:
        remaining = [img for img in all_images if img.id in kept_ids]
        group.primary_image_id = remaining[0].id if remaining else None

    # 5. Create split-off groups
    moving_image_map = {img.id: img for img in all_images if img.id in moving_ids}
    new_group_ids: list[int] = []
    for new_group_payload in payload.new_groups:
        new_group = ImageGroup(
            base_name=new_group_payload.base_name,
            author=new_group_payload.author,
        )
        db.add(new_group)
        db.flush()  # get new_group.id
        for img_id in new_group_payload.image_ids:
            image = moving_image_map.get(img_id)
            if image:
                image.group_id = new_group.id
                image.author = new_group_payload.author
        new_group.primary_image_id = (
            new_group_payload.image_ids[0] if new_group_payload.image_ids else None
        )
        new_group_ids.append(new_group.id)

    db.commit()
    pending.apply()
    return GroupEditResponse(
        id=group_id,
        new_group_ids=new_group_ids,
        deleted_image_ids=deleted_ids,
    )


@router.delete("/{group_id}")
@write_locked
def delete_group(
    group_id: int,
    db: Session = Depends(get_db),
):
    """Delete a group and all its images."""
    group = db.query(ImageGroup).filter(ImageGroup.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    images = db.query(Image).filter(Image.group_id == group_id).all()
    pending = delete_image_rows(db, images)
    # Bulk delete: the images are already gone, so there are no foreign keys to
    # null out (which db.delete(group) would load the collection to do).
    db.execute(delete(ImageGroup).where(ImageGroup.id == group_id))
    db.commit()
    pending.apply()
    return {"message": f"Group {group_id} and all its images deleted"}


@router.post("/{group_id}/move-images", response_model=MoveImagesResponse)
@write_locked
def move_images(
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
@write_locked
def merge_group(
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
