"""Search API endpoints."""

from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from ..models import (
    Color,
    Image,
    ImageSearchResponse,
    Tag,
    get_session_local,
)
from ..services import get_clip_service, qdrant_service

router = APIRouter()


def get_db(request: Request):
    """Dependency to get database session."""
    SessionLocal = get_session_local(request.app.state.db_engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/", response_model=ImageSearchResponse)
async def search_images(
    text: Optional[str] = None,
    semantic: Optional[str] = None,
    tags: List[str] = Query([]),
    exclude_tags: List[str] = Query([]),
    authors: List[str] = Query([]),
    colors: List[str] = Query([]),
    gridded: Optional[bool] = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db)
):
    """
    Multi-faceted image search with flexible filtering logic.

    Filtering logic:
    - Authors: OR (match any selected author)
    - Tags: OR within same category, AND across different categories
      Example: grid:gridded AND (season:winter OR season:summer)
    - Colors: OR (match any selected color)

    Args:
        text: Text search in name, filename, author
        semantic: Semantic search query (e.g., "dark forest cave")
        tags: Tag filters in format "category:value" (e.g., "season:winter")
        exclude_tags: Tags to exclude in format "category:value"
        authors: Filter by author names (OR logic)
        colors: Filter by hex colors (OR logic)
        limit: Maximum results
        offset: Result offset for pagination
    """
    # Debug logging
    print(f"\n=== Search parameters received ===")
    print(f"  text: {text}")
    print(f"  semantic: {semantic}")
    print(f"  tags: {tags}")
    print(f"  exclude_tags: {exclude_tags}")
    print(f"  authors: {authors}")
    print(f"  colors: {colors}")
    print(f"=================================\n")

    # Start with base query
    query = db.query(Image)

    # Text search
    if text:
        search_pattern = f"%{text}%"
        query = query.filter(
            or_(
                Image.name.ilike(search_pattern),
                Image.filename.ilike(search_pattern),
                Image.author.ilike(search_pattern)
            )
        )

    # Gridded filter
    if gridded is not None:
        query = query.filter(Image.gridded == gridded)

    # Author filter - OR logic (match any selected author)
    if authors:
        print(f"Applying author filter: {authors}")
        author_filters = [Image.author == author for author in authors]
        query = query.filter(or_(*author_filters))
        print(f"After author filter: {query.count()} images")

    # Tag filters - Group by category, OR within category, AND across categories
    if tags:
        print(f"Applying tag filters: {tags}")
        from collections import defaultdict
        tags_by_category = defaultdict(list)

        # Group tags by category
        for tag_filter in tags:
            if ":" in tag_filter:
                category, value = tag_filter.split(":", 1)
                tags_by_category[category].append(value)

        print(f"Tags grouped by category: {dict(tags_by_category)}")

        # Apply filters: OR within category, AND across categories
        for category, values in tags_by_category.items():
            # Create OR condition for values within this category
            # Build a single subquery that finds all image_ids matching any value in this category
            category_filter = or_(*[
                and_(Tag.category == category, Tag.value == value)
                for value in values
            ])

            # Create subquery of image IDs that match this category filter
            matching_image_ids = (
                db.query(Tag.image_id)
                .filter(category_filter)
                .distinct()
                .scalar_subquery()
            )

            # AND with main query - image must have at least one tag matching this category
            query = query.filter(
                Image.id.in_(
                    db.query(Tag.image_id).filter(category_filter).distinct()
                )
            )
            print(f"After applying {category} filter ({values}): {query.count()} images")

    # Exclude tags
    if exclude_tags:
        for tag_filter in exclude_tags:
            if ":" in tag_filter:
                category, value = tag_filter.split(":", 1)
                # Subquery to find images with excluded tags
                excluded_ids = db.query(Tag.image_id).filter(
                    and_(
                        Tag.category == category,
                        Tag.value == value
                    )
                ).subquery()
                query = query.filter(~Image.id.in_(excluded_ids))

    # Color filters
    if colors:
        # Find images that have any of the specified colors
        color_filters = [Color.color_hex == color for color in colors]
        query = query.join(Image.colors).filter(or_(*color_filters))

    # Semantic search using Qdrant
    image_ids_from_semantic = None
    semantic_scores = None
    if semantic:
        try:
            clip_service = get_clip_service()
            query_embedding = clip_service.encode_text(semantic)

            # Search in Qdrant
            qdrant_results = qdrant_service.search_similar(
                query_embedding=query_embedding,
                limit=limit * 2,  # Get more results to allow for filtering
                score_threshold=0.2,  # Minimum similarity threshold (lowered to match /semantic endpoint)
            )

            # Extract image IDs and scores
            image_ids_from_semantic = [r["image_id"] for r in qdrant_results]
            semantic_scores = {r["image_id"]: r["score"] for r in qdrant_results}

            if image_ids_from_semantic:
                query = query.filter(Image.id.in_(image_ids_from_semantic))
            else:
                # No semantic matches, return empty
                return ImageSearchResponse(
                    total=0,
                    limit=limit,
                    offset=offset,
                    images=[]
                )

        except Exception as e:
            # Log error and return error response for semantic search
            print(f"Semantic search error: {e}")
            import traceback
            traceback.print_exc()
            # Return empty results on error
            return ImageSearchResponse(
                total=0,
                limit=limit,
                offset=offset,
                images=[]
            )

    # Get total count before pagination
    total = query.count()
    print(f"Final query count: {total} images")

    # Apply pagination
    results = query.distinct().offset(offset).limit(limit).all()
    print(f"Returning {len(results)} images after pagination\n")

    # If semantic search was used, sort by semantic similarity
    if image_ids_from_semantic:
        # Create a mapping of image_id to position in semantic results
        id_to_position = {img_id: idx for idx, img_id in enumerate(image_ids_from_semantic)}
        # Sort results by semantic similarity
        results = sorted(results, key=lambda img: id_to_position.get(img.id, float('inf')))

    return ImageSearchResponse(
        total=total,
        limit=limit,
        offset=offset,
        images=results,
        scores=semantic_scores,
    )


@router.get("/semantic")
async def semantic_search(
    query: str,
    limit: int = 100,
    score_threshold: float = 0.7,
    db: Session = Depends(get_db)
):
    """
    Pure semantic search using CLIP embeddings.

    Args:
        query: Text query (e.g., "dark forest with river")
        limit: Maximum results
        score_threshold: Minimum similarity score (0.0-1.0)
    """
    try:
        clip_service = get_clip_service()
        query_embedding = clip_service.encode_text(query)

        qdrant_results = qdrant_service.search_similar(
            query_embedding=query_embedding,
            limit=limit,
            score_threshold=score_threshold,
        )

        # Fetch full Image objects from database
        image_ids = [r["image_id"] for r in qdrant_results]
        images_dict = {}
        if image_ids:
            images = db.query(Image).filter(Image.id.in_(image_ids)).all()
            images_dict = {img.id: img for img in images}

        # Combine Qdrant results with full Image objects
        results = []
        for qdrant_result in qdrant_results:
            image_id = qdrant_result["image_id"]
            if image_id in images_dict:
                results.append({
                    "image_id": image_id,
                    "score": qdrant_result["score"],
                    "image": images_dict[image_id]
                })

        return {
            "query": query,
            "total": len(results),
            "results": results,
            "error": None
        }

    except Exception as e:
        return {
            "error": str(e),
            "query": query,
            "total": 0,
            "results": [],
        }
