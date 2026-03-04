"""Tags API endpoints — CRUD for categories and tag values with cascade support."""

import json

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session, subqueryload

from ..models import (
    Image,
    Tag,
    TagCategory,
    TagCategoryCreate,
    TagCategoryResponse,
    TagCategoryUpdate,
    TagCreate,
    TagResponse,
    TagValueUpdate,
)
from .dependencies import get_db

router = APIRouter()


def _cascade_tag_change(db: Session, affected_image_ids: list[int]) -> None:
    """Reload affected images and rebuild their FTS search text + invalidate alias cache."""
    from ..services.fts_service import invalidate_alias_cache, rebuild_search_text

    if affected_image_ids:
        db.expire_all()
        affected_imgs = (
            db.query(Image)
            .options(subqueryload(Image.tags))
            .filter(Image.id.in_(affected_image_ids))
            .all()
        )
        for img in affected_imgs:
            rebuild_search_text(img, db)
    invalidate_alias_cache()


# ── Tag Categories ────────────────────────────────────────────────────────────


@router.get("/categories", response_model=list[TagCategoryResponse])
async def list_tag_categories(db: Session = Depends(get_db)):
    """List all tag categories, ordered by display_order."""
    categories = db.query(TagCategory).order_by(TagCategory.display_order, TagCategory.name).all()
    return categories


@router.post("/categories", response_model=TagCategoryResponse, status_code=201)
async def create_tag_category(payload: TagCategoryCreate, db: Session = Depends(get_db)):
    """Create a new tag category."""
    existing = db.query(TagCategory).filter(TagCategory.name == payload.name).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Category '{payload.name}' already exists")

    category = TagCategory(
        name=payload.name,
        description=payload.description,
        color=payload.color,
        display_order=payload.display_order,
        common_values=json.dumps([]),
    )
    db.add(category)
    db.commit()
    db.refresh(category)
    return category


@router.get("/categories/{category_name}", response_model=TagCategoryResponse)
async def get_tag_category(category_name: str, db: Session = Depends(get_db)):
    """Get a specific tag category by name."""
    category = db.query(TagCategory).filter(TagCategory.name == category_name).first()
    if not category:
        raise HTTPException(status_code=404, detail="Tag category not found")
    return category


@router.patch("/categories/{category_name}")
async def update_tag_category(
    category_name: str, payload: TagCategoryUpdate, db: Session = Depends(get_db)
):
    """Update a tag category. If name changes, cascades to all Tag rows."""
    category = db.query(TagCategory).filter(TagCategory.name == category_name).first()
    if not category:
        raise HTTPException(status_code=404, detail="Tag category not found")

    affected_images = 0

    # Rename — cascade to Tag table
    if payload.name is not None and payload.name != category.name:
        # Check for conflict
        conflict = db.query(TagCategory).filter(TagCategory.name == payload.name).first()
        if conflict:
            raise HTTPException(status_code=409, detail=f"Category '{payload.name}' already exists")

        affected_images = (
            db.query(func.count(func.distinct(Tag.image_id)))
            .filter(Tag.category == category_name)
            .scalar()
        ) or 0

        db.query(Tag).filter(Tag.category == category_name).update(
            {Tag.category: payload.name}, synchronize_session=False
        )
        category.name = payload.name

    if payload.description is not None:
        category.description = payload.description
    if payload.color is not None:
        category.color = payload.color
    if payload.icon is not None:
        category.icon = payload.icon
    if payload.display_order is not None:
        category.display_order = payload.display_order

    db.commit()
    db.refresh(category)
    return {
        "category": TagCategoryResponse.model_validate(category),
        "affected_images": affected_images,
    }


@router.delete("/categories/{category_name}")
async def delete_tag_category(category_name: str, db: Session = Depends(get_db)):
    """Delete a tag category and all tags on images in that category."""
    category = db.query(TagCategory).filter(TagCategory.name == category_name).first()
    if not category:
        raise HTTPException(status_code=404, detail="Tag category not found")

    affected_image_ids = [
        row[0]
        for row in db.query(Tag.image_id).filter(Tag.category == category_name).distinct().all()
    ]

    deleted_tags = (
        db.query(Tag).filter(Tag.category == category_name).delete(synchronize_session=False)
    )
    db.delete(category)
    _cascade_tag_change(db, affected_image_ids)
    db.commit()

    return {
        "message": f"Category '{category_name}' deleted",
        "deleted_tags": deleted_tags,
        "affected_images": len(affected_image_ids),
    }


# ── Tag Values within Categories ──────────────────────────────────────────────


@router.put("/categories/{category_name}/tags/{tag_name}", response_model=TagCategoryResponse)
async def upsert_tag_value(
    category_name: str,
    tag_name: str,
    aliases: list[str] | None = Body(None),
    db: Session = Depends(get_db),
):
    """Add a tag value to a category or update its aliases."""
    category = db.query(TagCategory).filter(TagCategory.name == category_name).first()
    if not category:
        raise HTTPException(status_code=404, detail="Tag category not found")

    values = json.loads(category.common_values or "[]")

    # Normalize all entries to object form
    normalized = []
    for v in values:
        if isinstance(v, str):
            normalized.append({"value": v, "aliases": []})
        else:
            normalized.append({"value": v["value"], "aliases": v.get("aliases", [])})

    # Update or insert
    updated = False
    for entry in normalized:
        if entry["value"] == tag_name:
            entry["aliases"] = aliases or []
            updated = True
            break

    if not updated:
        normalized.append({"value": tag_name, "aliases": aliases or []})

    category.common_values = json.dumps(normalized)
    db.commit()
    db.refresh(category)

    from ..services.fts_service import invalidate_alias_cache

    invalidate_alias_cache()
    return category


@router.patch("/categories/{category_name}/tags/{tag_name}")
async def rename_tag_value(
    category_name: str,
    tag_name: str,
    payload: TagValueUpdate,
    db: Session = Depends(get_db),
):
    """Rename a tag value. Cascades to all Tag rows with that category+value."""
    category = db.query(TagCategory).filter(TagCategory.name == category_name).first()
    if not category:
        raise HTTPException(status_code=404, detail="Tag category not found")

    new_value = payload.new_value.strip()
    if not new_value:
        raise HTTPException(status_code=400, detail="New value cannot be empty")

    # Update vocabulary
    values = json.loads(category.common_values or "[]")
    found = False
    for i, v in enumerate(values):
        val = v if isinstance(v, str) else v["value"]
        if val == tag_name:
            found = True
            if isinstance(v, str):
                values[i] = new_value
            else:
                v["value"] = new_value
            break

    if not found:
        raise HTTPException(status_code=404, detail=f"Tag value '{tag_name}' not found in category")

    category.common_values = json.dumps(values)

    # Cascade to Tag table
    affected_image_ids = [
        row[0]
        for row in db.query(Tag.image_id)
        .filter(Tag.category == category_name, Tag.value == tag_name)
        .distinct()
        .all()
    ]

    db.query(Tag).filter(Tag.category == category_name, Tag.value == tag_name).update(
        {Tag.value: new_value}, synchronize_session=False
    )
    _cascade_tag_change(db, affected_image_ids)
    db.commit()
    db.refresh(category)
    return {
        "category": TagCategoryResponse.model_validate(category),
        "old_value": tag_name,
        "new_value": new_value,
        "affected_images": len(affected_image_ids),
    }


@router.delete("/categories/{category_name}/tags/{tag_name}")
async def delete_tag_value(category_name: str, tag_name: str, db: Session = Depends(get_db)):
    """Delete a tag value from a category's vocabulary AND from all images."""
    category = db.query(TagCategory).filter(TagCategory.name == category_name).first()
    if not category:
        raise HTTPException(status_code=404, detail="Tag category not found")

    # Remove from vocabulary
    values = json.loads(category.common_values or "[]")
    original_len = len(values)
    values = [v for v in values if (v if isinstance(v, str) else v["value"]) != tag_name]
    if len(values) == original_len:
        raise HTTPException(status_code=404, detail="Tag not found in category vocabulary")

    category.common_values = json.dumps(values)

    # Cascade: delete from images
    affected_image_ids = [
        row[0]
        for row in db.query(Tag.image_id)
        .filter(Tag.category == category_name, Tag.value == tag_name)
        .distinct()
        .all()
    ]

    deleted_tags = (
        db.query(Tag)
        .filter(Tag.category == category_name, Tag.value == tag_name)
        .delete(synchronize_session=False)
    )
    _cascade_tag_change(db, affected_image_ids)
    db.commit()
    return {
        "message": f"Tag '{tag_name}' deleted from '{category_name}'",
        "deleted_tags": deleted_tags,
        "affected_images": len(affected_image_ids),
    }


# ── Per-Image Tag Operations ──────────────────────────────────────────────────


@router.get("/values/{category_name}")
async def get_tag_values_for_category(category_name: str, db: Session = Depends(get_db)):
    """Get all unique tag values used for a specific category."""
    tags = db.query(Tag).filter(Tag.category == category_name).all()
    values = list({tag.value for tag in tags})
    return {"category": category_name, "values": sorted(values)}


@router.get("/image/{image_id}", response_model=list[TagResponse])
async def get_image_tags(image_id: int, db: Session = Depends(get_db)):
    """Get all tags for a specific image."""
    tags = db.query(Tag).filter(Tag.image_id == image_id).all()
    return tags


@router.post("/image/{image_id}", response_model=TagResponse)
async def add_tag_to_image(image_id: int, tag: TagCreate, db: Session = Depends(get_db)):
    """Add a tag to an image."""
    from ..services.fts_service import rebuild_search_text

    new_tag = Tag(
        image_id=image_id,
        category=tag.category,
        value=tag.value,
        confidence=tag.confidence,
        source=tag.source,
    )
    db.add(new_tag)
    db.flush()  # persist tag so image.tags includes it

    image = db.query(Image).options(subqueryload(Image.tags)).filter(Image.id == image_id).first()
    if image:
        rebuild_search_text(image, db)

    db.commit()
    db.refresh(new_tag)
    return new_tag


@router.delete("/{tag_id}")
async def delete_tag(tag_id: int, db: Session = Depends(get_db)):
    """Delete a tag from an image."""
    from ..services.fts_service import rebuild_search_text

    tag = db.query(Tag).filter(Tag.id == tag_id).first()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")

    image_id = tag.image_id
    db.delete(tag)
    db.flush()  # remove tag so image.tags no longer includes it

    image = db.query(Image).options(subqueryload(Image.tags)).filter(Image.id == image_id).first()
    if image:
        rebuild_search_text(image, db)

    db.commit()
    return {"message": "Tag deleted successfully"}


# ── Statistics ────────────────────────────────────────────────────────────────


@router.get("/stats")
async def get_tag_statistics(db: Session = Depends(get_db)):
    """Get statistics about tag usage."""
    category_counts = (
        db.query(Tag.category, func.count(Tag.id).label("count")).group_by(Tag.category).all()
    )
    value_counts = (
        db.query(Tag.category, func.count(func.distinct(Tag.value)).label("unique_values"))
        .group_by(Tag.category)
        .all()
    )

    category_stats = {}
    for cat, count in category_counts:
        category_stats[cat] = {"total_tags": count}
    for cat, unique in value_counts:
        if cat in category_stats:
            category_stats[cat]["unique_values"] = unique

    return {"total_tags": db.query(Tag).count(), "categories": category_stats}


# ── Bulk Retag ────────────────────────────────────────────────────────────────


@router.post("/retag-all")
async def trigger_retag_all():
    """Trigger the retag_all_images job (fire-and-forget)."""
    from ...pipeline.retag_all_images import retag_all_images
    from ..services.job_runner import get_job_runner

    try:
        runner = get_job_runner()
        if runner.has_active_job("Retag all images"):
            raise HTTPException(status_code=409, detail="Retag job already in progress")
        job_id = runner.submit(retag_all_images, name="Retag all images")
        return {"job_id": job_id, "message": "Retag job started"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Could not start retag job: {e}") from e
