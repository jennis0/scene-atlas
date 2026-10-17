"""Search API endpoints. The search logic lives in ``services/search_service.py``."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from ..config import settings
from ..models import ImageSearchResponse
from ..models.schemas import GroupSearchResponse
from ..services import search_service
from ..services.search_service import SearchFilters, SearchMode, SemanticSearchUnavailable
from .dependencies import get_db
from .rate_limits import limiter

router = APIRouter()

_SORT_BY = Query("created_at", pattern="^(created_at|name|relevance)$")
_SORT_DIR = Query("desc", pattern="^(asc|desc)$")


def search_filters(
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
) -> SearchFilters:
    """Filter query parameters shared by both search endpoints."""
    return SearchFilters(
        image_types=tuple(image_types),
        media_types=tuple(media_types),
        gridded=gridded,
        gridded_unknown=gridded_unknown,
        grid_type=grid_type,
        authors=tuple(authors),
        exclude_authors=tuple(exclude_authors),
        tags=tuple(tags),
        exclude_tags=tuple(exclude_tags),
        colors=tuple(colors),
    )


def _semantic_unavailable() -> HTTPException:
    return HTTPException(
        status_code=503, detail="Semantic search failed and no text fallback available."
    )


@router.get("/facets")
def get_search_facets(db: Session = Depends(get_db)):
    """Return available filter options with image counts for the filter panel."""
    return search_service.get_facets(db)


@router.get("/", response_model=ImageSearchResponse)
def search_images(
    query: str | None = None,
    semantic_only: bool = False,
    text_only: bool = False,
    filters: SearchFilters = Depends(search_filters),
    limit: int = Query(500, ge=1, le=2000),
    offset: int = Query(0, ge=0),
    sort_by: str = _SORT_BY,
    sort_dir: str = _SORT_DIR,
    # Deprecated aliases for ``query``; ``semantic`` also implies semantic_only.
    text: str | None = None,
    semantic: str | None = None,
    db: Session = Depends(get_db),
):
    """Hybrid image search: FTS5 (BM25) and CLIP rankings merged by Reciprocal Rank Fusion.

    The frontend maps a ``~`` query prefix to ``semantic_only`` and ``=`` to
    ``text_only``. Without a query, returns the filtered images in sort order.
    Tags are OR within a category and AND across categories; colours are OR.
    """
    effective_query = query or text or semantic
    if not effective_query:
        return search_service.browse_images(db, filters, sort_by, sort_dir, limit, offset)
    mode = SearchMode.from_flags(
        text_only=text_only, semantic_only=semantic_only or bool(semantic and not query)
    )
    try:
        return search_service.search_images(
            db, effective_query, mode, filters, sort_by, sort_dir, limit, offset
        )
    except SemanticSearchUnavailable:
        raise _semantic_unavailable() from None


@router.get("/groups", response_model=GroupSearchResponse)
def search_groups(
    query: str | None = None,
    semantic_only: bool = False,
    text_only: bool = False,
    filters: SearchFilters = Depends(search_filters),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    sort_by: str = _SORT_BY,
    sort_dir: str = _SORT_DIR,
    include_all_image_ids: bool = Query(False),
    db: Session = Depends(get_db),
):
    """Group-level search returning groups with a hero image and mosaic.

    Without a query, groups are listed in ``sort_by`` order (relevance falls
    back to created_at). With a query, groups are ranked by their best-matching
    image and ``sort_by`` is ignored.
    """
    if not query:
        return search_service.browse_groups(
            db, filters, sort_by, sort_dir, limit, offset, include_all_image_ids
        )
    mode = SearchMode.from_flags(text_only=text_only, semantic_only=semantic_only)
    try:
        return search_service.search_groups(
            db, query, mode, filters, limit, offset, include_all_image_ids
        )
    except SemanticSearchUnavailable:
        raise _semantic_unavailable() from None


@router.post("/rebuild-embeddings")
@limiter.limit(lambda: settings.rate_limit_expensive)
def trigger_rebuild_embeddings(request: Request, force: bool = False):
    """Rebuild all embeddings (fire-and-forget background job).

    Deletes and recreates the LanceDB table, then re-encodes every image.
    Search will be unavailable while the rebuild is running.
    If force=False and collection is already populated, the rebuild is skipped.
    """
    from ...pipeline.write_new_embeddings import rebuild_all_embeddings
    from ..services.job_runner import get_job_runner

    try:
        runner = get_job_runner()
        if runner.has_active_job("Rebuild embeddings"):
            raise HTTPException(status_code=409, detail="Embedding rebuild already in progress")
        job_id = runner.submit(rebuild_all_embeddings, name="Rebuild embeddings", force=force)
        return {"job_id": job_id, "message": "Embedding rebuild started"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Could not start rebuild job: {e}") from e
