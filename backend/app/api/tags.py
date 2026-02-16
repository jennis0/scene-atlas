"""Tags API endpoints."""

from typing import List
import json
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..models import (
    Tag,
    TagCategory,
    TagCategoryResponse,
    TagCreate,
    TagResponse,
    get_session_local,
)

router = APIRouter()


def get_db(request: Request):
    """Dependency to get database session."""
    SessionLocal = get_session_local(request.app.state.db_engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/categories", response_model=List[TagCategoryResponse])
async def list_tag_categories(db: Session = Depends(get_db)):
    """List all tag categories."""
    categories = db.query(TagCategory).all()
    return categories

@router.put("/categories/{category_name}/tags/{tag_name}", response_model=TagCategoryResponse)
async def update_tag_in_category(
    category_name: str,
    tag_name: str,
    aliases: List[str] = None,
    db: Session = Depends(get_db)
):
    """Add a tag to a category or updates it's aliases."""
    category = db.query(TagCategory).filter(TagCategory.name == category_name).first()
    if not category:
        raise HTTPException(status_code=404, detail="Tag category not found")

    existing_tags = json.loads(category.common_values)
    updated_tags = [{'value': v, 'aliases': [] if isinstance(v, str) else v.get('aliases', [])} for v in existing_tags]
    updated = False
    for tag in updated_tags:
        if tag['value'] == tag_name:
            tag['aliases'] = aliases
            updated = True
            
    if not updated:
        updated_tags.append({'value': tag_name, 'aliases': aliases or []})
               
    category.common_values = json.dumps(updated_tags)
    db.commit()
    db.refresh(category)
        
    return category

@router.delete("/categories/{category_name}/tags/{tag_name}")
async def delete_tag_from_category(
    category_name: str,
    tag_name: str,
    db: Session = Depends(get_db)
):
    "Delete a tag from a category's common values list. This does not delete any tags from images, just removes it from the category's common values."
    category = db.query(TagCategory).filter(TagCategory.name == category_name).first()
    if not category:
        raise HTTPException(status_code=404, detail="Tag category not found")
    
    existing_tags = json.loads(category.common_values)
    updated_tags = []
    deleted = False
    for v in existing_tags:
        if isinstance(v, str):
            if v != tag_name:
                updated_tags.append(v)    
            else:
                deleted = True
        else:
            if v['value'] != tag_name:
                updated_tags.append(v)
            else:
                deleted = True
                
    if not deleted:
        raise HTTPException(status_code=404, detail="Tag not found in category")
    
    else:
        category.common_values = json.dumps(updated_tags)
        db.commit()
        db.refresh(category)
        return {"message": "Tag deleted from category successfully", "category": category_name, "tag": tag_name}
    
    
@router.get("/categories/{category_name}", response_model=TagCategoryResponse)
async def get_tag_category(
    category_name: str,
    db: Session = Depends(get_db)
):
    """Get a specific tag category by name."""
    category = db.query(TagCategory).filter(TagCategory.name == category_name).first()
    if not category:
        raise HTTPException(status_code=404, detail="Tag category not found")
    return category


@router.get("/values/{category_name}")
async def get_tag_values_for_category(
    category_name: str,
    db: Session = Depends(get_db)
):
    """Get all unique tag values used for a specific category."""
    tags = db.query(Tag).filter(Tag.category == category_name).distinct(Tag.value).all()
    values = list(set(tag.value for tag in tags))
    return {
        "category": category_name,
        "values": sorted(values)
    }


@router.get("/image/{image_id}", response_model=List[TagResponse])
async def get_image_tags(
    image_id: int,
    db: Session = Depends(get_db)
):
    """Get all tags for a specific image."""
    tags = db.query(Tag).filter(Tag.image_id == image_id).all()
    return tags


@router.post("/image/{image_id}", response_model=TagResponse)
async def add_tag_to_image(
    image_id: int,
    tag: TagCreate,
    db: Session = Depends(get_db)
):
    """Add a tag to an image."""
    new_tag = Tag(
        image_id=image_id,
        category=tag.category,
        value=tag.value,
        confidence=tag.confidence,
        source=tag.source,
    )
    db.add(new_tag)
    db.commit()
    db.refresh(new_tag)
    return new_tag


@router.delete("/{tag_id}")
async def delete_tag(
    tag_id: int,
    db: Session = Depends(get_db)
):
    """Delete a tag."""
    tag = db.query(Tag).filter(Tag.id == tag_id).first()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")

    db.delete(tag)
    db.commit()
    return {"message": "Tag deleted successfully"}


@router.get("/stats")
async def get_tag_statistics(db: Session = Depends(get_db)):
    """Get statistics about tag usage."""
    from sqlalchemy import func

    # Count tags by category
    category_counts = db.query(
        Tag.category,
        func.count(Tag.id).label("count")
    ).group_by(Tag.category).all()

    # Count unique values per category
    value_counts = db.query(
        Tag.category,
        func.count(func.distinct(Tag.value)).label("unique_values")
    ).group_by(Tag.category).all()

    category_stats = {}
    for cat, count in category_counts:
        category_stats[cat] = {"total_tags": count}

    for cat, unique in value_counts:
        if cat in category_stats:
            category_stats[cat]["unique_values"] = unique

    return {
        "total_tags": db.query(Tag).count(),
        "categories": category_stats
    }
