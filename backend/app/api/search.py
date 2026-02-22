"""Search API endpoints."""

import logging

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from ..models import (
    Color,
    Image,
    ImageSearchResponse,
    Tag,
    get_session_local,
)
from ..services import get_clip_service, qdrant_service
from ..services.fts_service import fts_search

router = APIRouter()

logger = logging.getLogger(__name__)


def get_db(request: Request):
    """Dependency to get database session."""
    SessionLocal = get_session_local(request.app.state.db_engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/facets")
async def get_search_facets(db: Session = Depends(get_db)):
    """Return available filter options with image counts for the filter panel."""

    # Authors sorted by image count descending
    authors = (
        db.query(Image.author, func.count(Image.id))
        .filter(Image.author.isnot(None), Image.author != "")
        .group_by(Image.author)
        .order_by(func.count(Image.id).desc())
        .all()
    )

    # Tags: category + value with distinct image counts
    tag_rows = (
        db.query(Tag.category, Tag.value, func.count(func.distinct(Tag.image_id)))
        .group_by(Tag.category, Tag.value)
        .order_by(Tag.category, func.count(func.distinct(Tag.image_id)).desc())
        .all()
    )
    tags_by_category: dict = {}
    for cat, val, count in tag_rows:
        tags_by_category.setdefault(cat, []).append({"value": val, "count": count})

    # Grid state counts
    gridded_count = db.query(func.count(Image.id)).filter(Image.gridded.is_(True)).scalar() or 0
    gridless_count = db.query(func.count(Image.id)).filter(Image.gridded.is_(False)).scalar() or 0
    unknown_count = db.query(func.count(Image.id)).filter(Image.gridded.is_(None)).scalar() or 0

    # Top 50 colors by distinct image count
    colors = (
        db.query(Color.color_hex, func.count(func.distinct(Color.image_id)))
        .group_by(Color.color_hex)
        .order_by(func.count(func.distinct(Color.image_id)).desc())
        .limit(50)
        .all()
    )

    total_images = db.query(func.count(Image.id)).scalar() or 0

    # Image type counts
    image_type_rows = (
        db.query(Image.image_type, func.count(Image.id))
        .group_by(Image.image_type)
        .all()
    )

    # Media type counts (image vs video)
    media_type_rows = (
        db.query(Image.media_type, func.count(Image.id))
        .group_by(Image.media_type)
        .all()
    )

    return {
        "total_images": total_images,
        "authors": [{"value": a, "count": c} for a, c in authors],
        "tags": tags_by_category,
        "gridded": {
            "gridded": gridded_count,
            "gridless": gridless_count,
            "unknown": unknown_count,
        },
        "colors": [{"hex": h, "count": c} for h, c in colors],
        "image_types": [{"value": t or "battlemap", "count": c} for t, c in image_type_rows],
        "media_types": [{"value": m or "image", "count": c} for m, c in media_type_rows],
    }


@router.get("/", response_model=ImageSearchResponse)
async def search_images(
    query: str | None = None,
    semantic_only: bool = False,
    text_only: bool = False,
    tags: list[str] = Query([]),
    exclude_tags: list[str] = Query([]),
    authors: list[str] = Query([]),
    exclude_authors: list[str] = Query([]),
    colors: list[str] = Query([]),
    image_types: list[str] = Query([]),
    media_types: list[str] = Query([]),
    gridded: bool | None = None,
    limit: int = 500,
    offset: int = 0,
    # Deprecated aliases kept for backward compat
    text: str | None = None,
    semantic: str | None = None,
    db: Session = Depends(get_db),
):
    """
    Hybrid image search combining FTS5 (BM25) text ranking and CLIP semantic search.

    Every query runs both text and semantic search. Results are merged by score:
      final_score = semantic_score + TEXT_BOOST * normalized_text_score

    Prefix query with '~' on the frontend to set semantic_only=True (skips FTS5).
    Prefix query with '=' on the frontend to set text_only=True (skips CLIP).

    Filter logic:
    - Tags: OR within same category, AND across categories
    - Authors / exclude_authors: OR within, applied as AND
    - Colors: OR
    """
    # Handle deprecated aliases
    effective_query = query or text or semantic
    if semantic and not query:
        semantic_only = True
    # text_only and semantic_only are mutually exclusive; text_only wins
    if text_only:
        semantic_only = False

    # --- Build base SQL filter query ---
    sql_query = db.query(Image)

    if image_types:
        sql_query = sql_query.filter(Image.image_type.in_(image_types))

    if media_types:
        sql_query = sql_query.filter(Image.media_type.in_(media_types))

    if gridded is not None:
        sql_query = sql_query.filter(Image.gridded == gridded)

    if authors:
        sql_query = sql_query.filter(or_(*[Image.author == a for a in authors]))

    if exclude_authors:
        sql_query = sql_query.filter(~Image.author.in_(exclude_authors))

    if tags:
        from collections import defaultdict

        tags_by_category: dict = defaultdict(list)
        for tag_filter in tags:
            if ":" in tag_filter:
                cat, val = tag_filter.split(":", 1)
                tags_by_category[cat].append(val)
        for category, values in tags_by_category.items():
            category_filter = or_(
                *[and_(Tag.category == category, Tag.value == value) for value in values]
            )
            sql_query = sql_query.filter(
                Image.id.in_(db.query(Tag.image_id).filter(category_filter).distinct())
            )

    if exclude_tags:
        for tag_filter in exclude_tags:
            if ":" in tag_filter:
                cat, val = tag_filter.split(":", 1)
                excluded_ids = (
                    db.query(Tag.image_id)
                    .filter(and_(Tag.category == cat, Tag.value == val))
                    .subquery()
                )
                sql_query = sql_query.filter(~Image.id.in_(excluded_ids))

    if colors:
        from ..services.color_search import color_index

        matching_ids = color_index.find_images_by_colors(db, colors)
        if matching_ids:
            sql_query = sql_query.filter(Image.id.in_(matching_ids))
        else:
            sql_query = sql_query.filter(Image.id == -1)  # No matches

    # --- No search query: return filtered results sorted by name ---
    if not effective_query:
        total = sql_query.count()
        results = sql_query.distinct().order_by(Image.name).offset(offset).limit(limit).all()
        return ImageSearchResponse(total=total, limit=limit, offset=offset, images=results)

    # --- Hybrid search: run FTS5 and semantic in parallel ---
    TEXT_BOOST = 0.15
    SEMANTIC_THRESHOLD = 0.15
    SEMANTIC_ONLY_THRESHOLD = 0.15

    # FTS5 text search (skip if semantic_only)
    text_scores: dict[int, float] = {}
    if not semantic_only:
        fts_results = fts_search(db, effective_query, limit=limit * 3)
        if fts_results:
            # Normalize BM25 scores (negative) to 0-1: best (most negative) → 1.0
            min_bm25 = min(score for _, score in fts_results)  # most negative = best
            for image_id, bm25 in fts_results:
                # Normalize: 1.0 for best match, approaching 0 for poor matches
                text_scores[image_id] = bm25 / min_bm25 if min_bm25 != 0 else 0.0

    # CLIP semantic search (skipped in text_only mode)
    semantic_scores: dict[int, float] = {}
    if not text_only:
        try:
            clip_service = get_clip_service()
            query_embedding = clip_service.encode_text(effective_query)
            threshold = SEMANTIC_ONLY_THRESHOLD if semantic_only else SEMANTIC_THRESHOLD
            qdrant_results = qdrant_service.search_similar(
                query_embedding=query_embedding,
                limit=limit * 3,
                score_threshold=threshold,
            )
            semantic_scores = {r["image_id"]: r["score"] for r in qdrant_results}
        except Exception:
            logger.exception("Semantic search error")

    # Merge scores
    all_candidate_ids = set(text_scores.keys()) | set(semantic_scores.keys())

    if not all_candidate_ids:
        return ImageSearchResponse(total=0, limit=limit, offset=offset, images=[])

    merged_scores: dict[int, float] = {}
    for image_id in all_candidate_ids:
        sem = semantic_scores.get(image_id, 0.0)
        txt = text_scores.get(image_id, 0.0)

        # Drop pure-semantic results below threshold (text matches always included)
        if image_id not in text_scores and sem < (
            SEMANTIC_ONLY_THRESHOLD if semantic_only else SEMANTIC_THRESHOLD
        ):
            continue

        merged_scores[image_id] = sem + (TEXT_BOOST * txt if txt > 0 else 0.0)

    if not merged_scores:
        return ImageSearchResponse(total=0, limit=limit, offset=offset, images=[])

    # Apply SQL filters to the candidate set
    candidate_ids = list(merged_scores.keys())
    sql_query = sql_query.filter(Image.id.in_(candidate_ids))
    filtered_images = sql_query.distinct().all()

    # Sort by merged score descending
    filtered_images.sort(key=lambda img: merged_scores.get(img.id, 0.0), reverse=True)

    total = len(filtered_images)
    results = filtered_images[offset : offset + limit]

    # Return only scores for returned images
    returned_scores = {img.id: merged_scores.get(img.id, 0.0) for img in results}

    return ImageSearchResponse(
        total=total,
        limit=limit,
        offset=offset,
        images=results,
        scores=returned_scores,
    )
