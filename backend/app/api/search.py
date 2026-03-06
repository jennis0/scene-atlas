"""Search API endpoints."""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session, joinedload, subqueryload

from ..models import (
    Color,
    Image,
    ImageSearchResponse,
    Tag,
)
from ..services import get_clip_service, get_qdrant_service
from ..services.fts_service import fts_search, fts_search_terms, get_alias_expansions
from .dependencies import get_db

router = APIRouter()

logger = logging.getLogger(__name__)


@router.get("/facets")
def get_search_facets(db: Session = Depends(get_db)):
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
        .join(Image, Image.id == Tag.image_id)
        .group_by(Tag.category, Tag.value)
        .order_by(Tag.category, func.count(func.distinct(Tag.image_id)).desc())
        .all()
    )
    tags_by_category: dict = {}
    for cat, val, count in tag_rows:
        tags_by_category.setdefault(cat, []).append({"value": val, "count": count})

    # Grid state counts — one GROUP BY query instead of five COUNT queries
    grid_rows = (
        db.query(Image.gridded, Image.grid_type, func.count(Image.id))
        .group_by(Image.gridded, Image.grid_type)
        .all()
    )
    gridded_count = 0
    gridless_count = 0
    unknown_count = 0
    square_count = 0
    hex_count = 0
    for gridded_val, grid_type_val, cnt in grid_rows:
        if gridded_val is True:
            gridded_count += cnt
            if grid_type_val == "square":
                square_count += cnt
            elif grid_type_val == "hex":
                hex_count += cnt
        elif gridded_val is False:
            gridless_count += cnt
        else:
            unknown_count += cnt

    # Top 50 colors by distinct image count
    colors = (
        db.query(Color.color_hex, func.count(func.distinct(Color.image_id)))
        .join(Image, Image.id == Color.image_id)
        .group_by(Color.color_hex)
        .order_by(func.count(func.distinct(Color.image_id)).desc())
        .limit(50)
        .all()
    )

    total_images = db.query(func.count(Image.id)).scalar() or 0

    # Image type counts
    image_type_rows = (
        db.query(Image.image_type, func.count(Image.id)).group_by(Image.image_type).all()
    )

    # Media type counts (image vs video)
    media_type_rows = (
        db.query(Image.media_type, func.count(Image.id)).group_by(Image.media_type).all()
    )

    return {
        "total_images": total_images,
        "authors": [{"value": a, "count": c} for a, c in authors],
        "tags": tags_by_category,
        "gridded": {
            "gridded": gridded_count,
            "gridless": gridless_count,
            "unknown": unknown_count,
            "square": square_count,
            "hex": hex_count,
        },
        "colors": [{"hex": h, "count": c} for h, c in colors],
        "image_types": [{"value": t or "battlemap", "count": c} for t, c in image_type_rows],
        "media_types": [{"value": m or "image", "count": c} for m, c in media_type_rows],
    }


@router.get("/", response_model=ImageSearchResponse)
def search_images(
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
    gridded_unknown: bool = False,
    grid_type: str | None = None,
    limit: int = Query(500, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    sort_by: str = Query("created_at", pattern="^(created_at|name|relevance)$"),
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
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
    # Use subqueryload (not joinedload) to avoid inflating rows when combined
    # with .distinct() — joinedload uses LEFT OUTER JOIN which creates duplicate
    # rows that break DISTINCT and pagination.
    sql_query = db.query(Image).options(
        subqueryload(Image.tags),
        subqueryload(Image.colors),
        joinedload(Image.group),
    )

    if image_types:
        sql_query = sql_query.filter(Image.image_type.in_(image_types))

    if media_types:
        sql_query = sql_query.filter(Image.media_type.in_(media_types))

    if gridded_unknown:
        sql_query = sql_query.filter(Image.gridded.is_(None))
    elif gridded is not None:
        sql_query = sql_query.filter(Image.gridded == gridded)

    if grid_type is not None:
        sql_query = sql_query.filter(Image.grid_type == grid_type)

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

    # --- No search query: return filtered results with requested sort ---
    if not effective_query:
        # Relevance is meaningless without a query — fall back to created_at DESC
        effective_sort = sort_by if sort_by != "relevance" else "created_at"
        effective_dir = sort_dir if sort_by != "relevance" else "desc"

        col = Image.created_at if effective_sort == "created_at" else Image.name
        order = col.desc() if effective_dir == "desc" else col.asc()

        total = sql_query.count()
        results = (
            sql_query.distinct().order_by(order, Image.id.desc()).offset(offset).limit(limit).all()
        )
        return ImageSearchResponse(total=total, limit=limit, offset=offset, images=results)

    # --- Hybrid search: FTS5, alias expansion, and CLIP semantic ---
    SEMANTIC_THRESHOLD = 0.15
    SEMANTIC_ONLY_THRESHOLD = 0.15
    RRF_K = 60  # standard dampening constant for Reciprocal Rank Fusion
    RRF_TEXT_WEIGHT = 1.1  # text ranks weighted vs semantic 1×
    RRF_ALIAS_WEIGHT = 0.5

    # FTS5 text search (skip if semantic_only)
    text_scores: dict[int, float] = {}
    if not semantic_only:
        fts_results = fts_search(db, effective_query, limit=limit * 10)
        text_scores = dict(fts_results)

    # Alias expansion: separate FTS5 pass so alias matches don't dilute BM25 scores
    alias_scores: dict[int, float] = {}
    if not semantic_only and text_scores:
        alias_terms = get_alias_expansions(effective_query, db)
        if alias_terms:
            # Use fts_search_terms (not fts_search) to preserve OR semantics —
            # _sanitize_fts_query inside fts_search strips OR operators.
            alias_results = fts_search_terms(db, alias_terms, limit=limit * 3)
            alias_scores = dict(alias_results)

    # CLIP semantic search (skipped in text_only mode)
    semantic_scores: dict[int, float] = {}
    if not text_only:
        try:
            clip_service = get_clip_service()
            query_embedding = clip_service.encode_text(effective_query)
            threshold = SEMANTIC_ONLY_THRESHOLD if semantic_only else SEMANTIC_THRESHOLD
            qdrant_results = get_qdrant_service().search_similar(
                query_embedding=query_embedding,
                limit=limit * 3,
                score_threshold=threshold,
            )
            semantic_scores = {r["image_id"]: r["score"] for r in qdrant_results}
        except Exception:
            logger.exception("Semantic search error")

    # Reciprocal Rank Fusion across three ranked lists
    all_candidate_ids = (
        set(text_scores.keys()) | set(alias_scores.keys()) | set(semantic_scores.keys())
    )

    if not all_candidate_ids:
        return ImageSearchResponse(total=0, limit=limit, offset=offset, images=[])

    # Build rank maps (rank 0 = best)
    sem_ranked = sorted(semantic_scores, key=semantic_scores.get, reverse=True)  # type: ignore[arg-type]
    txt_ranked = sorted(
        text_scores, key=text_scores.get
    )  # BM25 scores are negative; lower = better
    alias_ranked = sorted(alias_scores, key=alias_scores.get)  # same

    sem_rank = {img_id: rank for rank, img_id in enumerate(sem_ranked)}
    txt_rank = {img_id: rank for rank, img_id in enumerate(txt_ranked)}
    alias_rank = {img_id: rank for rank, img_id in enumerate(alias_ranked)}

    merged_scores: dict[int, float] = {}
    for image_id in all_candidate_ids:
        score = 0.0
        if image_id in sem_rank:
            score += 1.0 / (RRF_K + sem_rank[image_id])
        if image_id in txt_rank:
            score += RRF_TEXT_WEIGHT / (RRF_K + txt_rank[image_id])
        if image_id in alias_rank:
            score += RRF_ALIAS_WEIGHT / (RRF_K + alias_rank[image_id])
        merged_scores[image_id] = score

    if not merged_scores:
        return ImageSearchResponse(total=0, limit=limit, offset=offset, images=[])

    # Normalize RRF scores to [0, 1] so the frontend relevance threshold works.
    # Raw RRF scores are tiny (~0.01–0.05); without normalization the threshold
    # slider (default 0.2) would filter out every result.
    max_rrf = max(merged_scores.values())
    if max_rrf > 0:
        merged_scores = {img_id: s / max_rrf for img_id, s in merged_scores.items()}

    # Apply SQL filters to the candidate set
    candidate_ids = list(merged_scores.keys())
    sql_query = sql_query.filter(Image.id.in_(candidate_ids))
    filtered_images = sql_query.distinct().all()

    # Sort by requested field
    if sort_by == "relevance":
        filtered_images.sort(key=lambda img: (merged_scores.get(img.id, 0.0), img.id), reverse=True)
    elif sort_by == "created_at":
        filtered_images.sort(
            key=lambda img: (img.created_at or datetime.min, img.id),
            reverse=(sort_dir == "desc"),
        )
    elif sort_by == "name":
        filtered_images.sort(
            key=lambda img: ((img.name or "").lower(), img.id),
            reverse=(sort_dir == "desc"),
        )

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


# ── Admin: Rebuild Embeddings ────────────────────────────────────────────────


@router.post("/rebuild-embeddings")
def trigger_rebuild_embeddings():
    """Rebuild all CLIP embeddings (fire-and-forget background job).

    Deletes and recreates the Qdrant collection, then re-encodes every image.
    Search will be unavailable while the rebuild is running.
    """
    from ...pipeline.write_new_embeddings import rebuild_all_embeddings
    from ..services.job_runner import get_job_runner

    try:
        runner = get_job_runner()
        if runner.has_active_job("Rebuild embeddings"):
            raise HTTPException(status_code=409, detail="Embedding rebuild already in progress")
        job_id = runner.submit(rebuild_all_embeddings, name="Rebuild embeddings")
        return {"job_id": job_id, "message": "Embedding rebuild started"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Could not start rebuild job: {e}") from e
