"""Hybrid image and group search (design/search.md).

A query is ranked three ways (FTS5 BM25, alias-expanded FTS5, CLIP similarity),
the rankings are merged with Reciprocal Rank Fusion, and the merged candidates
are narrowed by the SQL filters. Without a query, filtered results are listed
in the requested order.

Candidates are filtered and sorted as lightweight ``(id, sort key)`` rows; full
Image objects (with tags, colours and group) are loaded only for the page being
returned, in a fixed number of queries.
"""

from __future__ import annotations

import enum
import json
import logging
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, joinedload, selectinload
from sqlalchemy.sql.elements import ColumnElement

from ..models import Color, Image, ImageGroup, ImageResponse, ImageSearchResponse, Tag
from ..models.schemas import GroupSearchResponse, GroupSearchResult
from . import get_clip_service, get_lancedb_service
from .app_settings import get_settings as get_app_settings
from .clip_service import get_effective_model_name
from .color_search import color_match_ids
from .fts_service import fts_search, fts_search_terms, get_alias_expansions
from .model_registry import get_semantic_threshold

logger = logging.getLogger(__name__)

RRF_K = 60  # standard Reciprocal Rank Fusion dampening constant
RRF_SEMANTIC_WEIGHT = 1.0
RRF_TEXT_WEIGHT = 1.1
RRF_ALIAS_WEIGHT = 0.5  # synonyms must not outrank the words the user typed
GROUP_CANDIDATE_MIN = 1000
MOSAIC_SIZE = 4


class SemanticSearchUnavailable(Exception):
    """Semantic-only search failed, so there is nothing to fall back to."""


class SearchMode(enum.Enum):
    HYBRID = "hybrid"
    TEXT = "text"
    SEMANTIC = "semantic"

    @classmethod
    def from_flags(cls, *, text_only: bool, semantic_only: bool) -> SearchMode:
        if text_only:  # the two flags are exclusive; text-only wins
            return cls.TEXT
        return cls.SEMANTIC if semantic_only else cls.HYBRID


@dataclass(frozen=True)
class SearchFilters:
    """Filters shared by image and group search.

    Tags are ``category:value`` strings: OR within a category, AND across
    categories. Entries without a colon are ignored.
    """

    image_types: tuple[str, ...] = ()
    media_types: tuple[str, ...] = ()
    gridded: bool | None = None
    gridded_unknown: bool = False  # takes precedence over ``gridded``
    grid_type: str | None = None
    authors: tuple[str, ...] = ()
    exclude_authors: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    exclude_tags: tuple[str, ...] = ()
    colors: tuple[str, ...] = ()


@dataclass(frozen=True)
class CandidatePools:
    """How many results each ranking contributes before filtering."""

    text: int
    alias: int
    semantic: int


def id_set(ids: Iterable[int]) -> Select:
    """An ``IN`` operand for any number of ids, passed as one JSON parameter.

    SQLite caps bound parameters per statement (32766 by default). Search
    candidates can exceed that on a large library, so they must not be bound
    one parameter per id.
    """
    values = func.json_each(json.dumps(sorted(ids))).table_valued("value")
    return select(values.c.value)


# Filters


def _split_tag(tag: str) -> tuple[str, str] | None:
    if ":" not in tag:
        return None
    category, value = tag.split(":", 1)
    return category, value


def _tags_by_category(tags: Iterable[str]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for tag in tags:
        parsed = _split_tag(tag)
        if parsed:
            grouped.setdefault(parsed[0], []).append(parsed[1])
    return grouped


def _image_property_conditions(db: Session, filters: SearchFilters) -> list[ColumnElement[bool]]:
    """One condition per filter on a single image (authors excluded, see callers).

    Group browse applies each condition separately ("the group has an image
    that..."), so they must stay independent of each other.
    """
    conditions: list[ColumnElement[bool]] = []
    if filters.image_types:
        conditions.append(Image.image_type.in_(filters.image_types))
    if filters.media_types:
        conditions.append(Image.media_type.in_(filters.media_types))
    if filters.gridded_unknown:
        conditions.append(Image.gridded.is_(None))
    elif filters.gridded is not None:
        conditions.append(Image.gridded == filters.gridded)
    if filters.grid_type is not None:
        conditions.append(Image.grid_type == filters.grid_type)
    for category, values in _tags_by_category(filters.tags).items():
        tagged = select(Tag.image_id).where(Tag.category == category, Tag.value.in_(values))
        conditions.append(Image.id.in_(tagged))
    for tag in filters.exclude_tags:
        parsed = _split_tag(tag)
        if parsed:
            tagged = select(Tag.image_id).where(Tag.category == parsed[0], Tag.value == parsed[1])
            conditions.append(Image.id.not_in(tagged))
    if filters.colors:
        threshold = get_app_settings(db).color_distance_threshold
        conditions.append(Image.id.in_(color_match_ids(filters.colors, threshold)))
    return conditions


def image_conditions(db: Session, filters: SearchFilters) -> list[ColumnElement[bool]]:
    """WHERE conditions on ``Image`` for all filters."""
    conditions = _image_property_conditions(db, filters)
    if filters.authors:
        conditions.append(Image.author.in_(filters.authors))
    if filters.exclude_authors:
        conditions.append(Image.author.not_in(filters.exclude_authors))
    return conditions


def group_conditions(db: Session, filters: SearchFilters) -> list[ColumnElement[bool]]:
    """WHERE conditions on ``ImageGroup`` for browsing groups.

    Authors match the group's own author. Every other filter keeps groups with
    at least one matching image, each filter independently: an exclude-tag
    filter keeps groups that have any image without that tag.
    """
    conditions: list[ColumnElement[bool]] = [
        ImageGroup.id.in_(select(Image.group_id).where(condition))
        for condition in _image_property_conditions(db, filters)
    ]
    if filters.authors:
        conditions.append(ImageGroup.author.in_(filters.authors))
    if filters.exclude_authors:
        conditions.append(ImageGroup.author.not_in(filters.exclude_authors))
    return conditions


# Ranking


def _semantic_scores(query: str, limit: int, *, required: bool) -> dict[int, float]:
    """CLIP similarity scores. A failure is non-fatal unless semantic search is all we have."""
    try:
        embedding = get_clip_service().encode_text(query)
        results = get_lancedb_service().search_similar(
            embedding,
            limit=limit,
            score_threshold=get_semantic_threshold(get_effective_model_name()),
        )
    except Exception as exc:
        logger.exception("Semantic search error")
        if required:
            raise SemanticSearchUnavailable from exc
        return {}
    return {r["image_id"]: r["score"] for r in results}


def fuse_rankings(
    text_scores: dict[int, float],
    alias_scores: dict[int, float],
    semantic_scores: dict[int, float],
) -> dict[int, float]:
    """Reciprocal Rank Fusion: each list adds ``weight / (RRF_K + rank)``, rank 0 = best.

    BM25 scores are negative (lower is better); similarity is higher-is-better.
    """
    merged: dict[int, float] = {}
    for scores, weight, higher_is_better in (
        (semantic_scores, RRF_SEMANTIC_WEIGHT, True),
        (text_scores, RRF_TEXT_WEIGHT, False),
        (alias_scores, RRF_ALIAS_WEIGHT, False),
    ):
        ranked = sorted(scores, key=scores.__getitem__, reverse=higher_is_better)
        for rank, image_id in enumerate(ranked):
            merged[image_id] = merged.get(image_id, 0.0) + weight / (RRF_K + rank)
    return merged


def rank_candidates(
    db: Session, query: str, mode: SearchMode, pools: CandidatePools
) -> dict[int, float]:
    """Fused relevance score per candidate image id (unfiltered).

    Raises SemanticSearchUnavailable when semantic-only search fails.
    """
    text_scores: dict[int, float] = {}
    alias_scores: dict[int, float] = {}
    if mode is not SearchMode.SEMANTIC:
        text_scores = dict(fts_search(db, query, limit=pools.text))
    if text_scores:
        # A separate pass, so synonym matches don't dilute the BM25 scores of the
        # words the user typed. fts_search would strip the OR operators it needs.
        alias_terms = get_alias_expansions(query, db)
        if alias_terms:
            alias_scores = dict(fts_search_terms(db, alias_terms, limit=pools.alias))
    semantic_scores: dict[int, float] = {}
    if mode is not SearchMode.TEXT:
        semantic_scores = _semantic_scores(
            query, pools.semantic, required=mode is SearchMode.SEMANTIC
        )
    return fuse_rankings(text_scores, alias_scores, semantic_scores)


# Loading


def _load_images(db: Session, ids: Collection[int]) -> dict[int, Image]:
    """Full Image objects (tags, colours, group) by id, in a fixed number of queries."""
    if not ids:
        return {}
    stmt = (
        select(Image)
        .options(selectinload(Image.tags), selectinload(Image.colors), joinedload(Image.group))
        .where(Image.id.in_(id_set(ids)))
    )
    return {image.id: image for image in db.scalars(stmt).unique()}


def _first_images_per_group(
    db: Session,
    group_ids: Collection[int],
    count: int,
    order_by,
    exclude_ids: Collection[int] = (),
) -> dict[int, list[int]]:
    """The first ``count`` image ids of each group in ``order_by`` order, in one query."""
    if not group_ids:
        return {}
    position = func.row_number().over(partition_by=Image.group_id, order_by=order_by)
    ranked = select(Image.id, Image.group_id, position.label("position")).where(
        Image.group_id.in_(group_ids)
    )
    if exclude_ids:
        ranked = ranked.where(Image.id.not_in(id_set(exclude_ids)))
    sub = ranked.subquery()
    rows = db.execute(
        select(sub.c.id, sub.c.group_id)
        .where(sub.c.position <= count)
        .order_by(sub.c.group_id, sub.c.position)
    )
    first: dict[int, list[int]] = {}
    for image_id, group_id in rows:
        first.setdefault(group_id, []).append(image_id)
    return first


def _in_order(images: dict[int, Image], ids: Iterable[int]) -> list[ImageResponse]:
    """``images`` in ``ids`` order, skipping any deleted since the ids were read."""
    return [ImageResponse.model_validate(images[i]) for i in ids if i in images]


def _order(column, sort_dir: str):
    return column.asc() if sort_dir == "asc" else column.desc()


# Image search


def browse_images(
    db: Session, filters: SearchFilters, sort_by: str, sort_dir: str, limit: int, offset: int
) -> ImageSearchResponse:
    """Filtered images without a query. Relevance falls back to newest first."""
    if sort_by == "relevance":
        sort_by, sort_dir = "created_at", "desc"
    column = Image.created_at if sort_by == "created_at" else Image.name
    conditions = image_conditions(db, filters)
    total = db.scalar(select(func.count()).select_from(Image).where(*conditions)) or 0
    page_ids = db.scalars(
        select(Image.id)
        .where(*conditions)
        .order_by(_order(column, sort_dir), Image.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return ImageSearchResponse(
        total=total,
        limit=limit,
        offset=offset,
        images=_in_order(_load_images(db, page_ids), page_ids),
    )


def _hybrid_sort_key(sort_by: str):
    if sort_by == "relevance":
        return None
    if sort_by == "name":
        return lambda row: ((row.name or "").lower(), row.id)
    return lambda row: (row.created_at or datetime.min, row.id)


def search_images(
    db: Session,
    query: str,
    mode: SearchMode,
    filters: SearchFilters,
    sort_by: str,
    sort_dir: str,
    limit: int,
    offset: int,
) -> ImageSearchResponse:
    """Images matching a query, with their fused relevance scores."""
    scores = rank_candidates(
        db, query, mode, CandidatePools(text=limit * 10, alias=limit * 3, semantic=limit * 3)
    )
    if not scores:
        return ImageSearchResponse(total=0, limit=limit, offset=offset, images=[])

    rows = list(
        db.execute(
            select(Image.id, Image.name, Image.created_at).where(
                *image_conditions(db, filters), Image.id.in_(id_set(scores))
            )
        )
    )
    key = _hybrid_sort_key(sort_by)
    if key is None:
        rows.sort(key=lambda row: (scores[row.id], row.id), reverse=True)
    else:
        rows.sort(key=key, reverse=sort_dir == "desc")

    page_ids = [row.id for row in rows[offset : offset + limit]]
    images = _in_order(_load_images(db, page_ids), page_ids)
    return ImageSearchResponse(
        total=len(rows),
        limit=limit,
        offset=offset,
        images=images,
        # Fused (not raw CLIP) scores drive the client's relevance slider, so
        # text matches with a weak visual match still pass it.
        scores={image.id: scores[image.id] for image in images},
    )


# Group search


def browse_groups(
    db: Session,
    filters: SearchFilters,
    sort_by: str,
    sort_dir: str,
    limit: int,
    offset: int,
    include_all_image_ids: bool,
) -> GroupSearchResponse:
    """Groups without a query; every image of a group counts as matching.

    The hero is the group's primary image, else its first image by id; the
    mosaic is the next images by id. Groups without images are counted in
    ``total_groups`` but not returned.
    """
    conditions = group_conditions(db, filters)
    total = db.scalar(select(func.count()).select_from(ImageGroup).where(*conditions)) or 0
    column = ImageGroup.base_name if sort_by == "name" else ImageGroup.created_at
    groups = db.scalars(
        select(ImageGroup)
        .where(*conditions)
        .order_by(_order(column, sort_dir))
        .limit(limit)
        .offset(offset)
    ).all()

    # One more than the mosaic, in case the primary image is among the first.
    first = _first_images_per_group(db, [g.id for g in groups], MOSAIC_SIZE + 1, Image.id)
    primary_ids = {g.primary_image_id for g in groups if g.primary_image_id}
    images = _load_images(db, primary_ids | {i for ids in first.values() for i in ids})

    results: list[GroupSearchResult] = []
    for group in groups:
        group_first = first.get(group.id, [])
        hero = images.get(group.primary_image_id) if group.primary_image_id else None
        if hero is None and group_first:
            hero = images.get(group_first[0])
        if hero is None:
            continue
        mosaic = _in_order(images, [i for i in group_first if i != hero.id])[:MOSAIC_SIZE]
        results.append(
            GroupSearchResult(
                group_id=group.id,
                base_name=group.base_name,
                author=group.author,
                hero_image=ImageResponse.model_validate(hero),
                mosaic_images=mosaic,
                total_scenes=group.image_count,
                matching_scenes=group.image_count,
                best_score=None,
            )
        )

    if include_all_image_ids and results:
        _attach_all_image_ids(db, results, filters.image_types)
    return GroupSearchResponse(total_groups=total, limit=limit, offset=offset, groups=results)


def _attach_all_image_ids(
    db: Session, results: list[GroupSearchResult], image_types: tuple[str, ...]
) -> None:
    """Every image id of each returned group (only of the selected types, if any)."""
    stmt = select(Image.group_id, Image.id).where(Image.group_id.in_([r.group_id for r in results]))
    if image_types:
        stmt = stmt.where(Image.image_type.in_(image_types))
    ids_by_group: dict[int, list[int]] = {}
    for group_id, image_id in db.execute(stmt.order_by(Image.id)):
        ids_by_group.setdefault(group_id, []).append(image_id)
    for result in results:
        result.all_image_ids = ids_by_group.get(result.group_id, [])


def search_groups(
    db: Session,
    query: str,
    mode: SearchMode,
    filters: SearchFilters,
    limit: int,
    offset: int,
    include_all_image_ids: bool,
) -> GroupSearchResponse:
    """Groups containing images that match a query, best match first.

    Matching images are collapsed by group. The hero is the group's best match;
    the mosaic is its next best matches, topped up with the group's newest
    other images. ``total_groups`` counts groups among the candidates, so on a
    very large library it can be a lower bound.
    """
    pool = max(limit * 20, GROUP_CANDIDATE_MIN)
    scores = rank_candidates(db, query, mode, CandidatePools(pool, pool, pool))
    if not scores:
        return GroupSearchResponse(total_groups=0, limit=limit, offset=offset, groups=[])

    rows = db.execute(
        select(Image.id, Image.group_id)
        .where(*image_conditions(db, filters), Image.id.in_(id_set(scores)))
        .order_by(Image.id)
    )
    # Ungrouped images collapse under None: counted in total_groups, never returned.
    matches: dict[int | None, list[tuple[int, float]]] = {}
    for image_id, group_id in rows:
        matches.setdefault(group_id, []).append((image_id, scores[image_id]))
    for group_matches in matches.values():
        group_matches.sort(key=lambda match: match[1], reverse=True)
    ranked = sorted(matches, key=lambda g: matches[g][0][1], reverse=True)
    page = [g for g in ranked[offset : offset + limit] if g is not None]

    groups = {g.id: g for g in db.scalars(select(ImageGroup).where(ImageGroup.id.in_(page)))}
    shown = {gid: [i for i, _ in matches[gid][: MOSAIC_SIZE + 1]] for gid in page if gid in groups}
    needs_fill = [gid for gid, ids in shown.items() if len(ids) <= MOSAIC_SIZE]
    fill = _first_images_per_group(
        db,
        needs_fill,
        MOSAIC_SIZE,
        (Image.created_at.desc(), Image.id.desc()),
        exclude_ids=[i for gid in needs_fill for i in shown[gid]],
    )
    images = _load_images(db, {i for ids in [*shown.values(), *fill.values()] for i in ids})

    results: list[GroupSearchResult] = []
    for gid, ids in shown.items():
        group = groups[gid]
        hero_id, *mosaic_ids = ids
        mosaic_ids += fill.get(gid, [])[: MOSAIC_SIZE - len(mosaic_ids)]
        if hero_id not in images:  # deleted since it was ranked
            continue
        results.append(
            GroupSearchResult(
                group_id=gid,
                base_name=group.base_name,
                author=group.author,
                hero_image=ImageResponse.model_validate(images[hero_id]),
                mosaic_images=_in_order(images, mosaic_ids),
                total_scenes=group.image_count,
                matching_scenes=len(matches[gid]),
                best_score=matches[gid][0][1],
                # Only matching images: Edit All marks the rest of the group out of scope.
                all_image_ids=[i for i, _ in matches[gid]] if include_all_image_ids else None,
            )
        )
    return GroupSearchResponse(total_groups=len(ranked), limit=limit, offset=offset, groups=results)


# Facets


def get_facets(db: Session) -> dict:
    """Filter options with image counts, for the filter panel."""
    image_count = func.count(Image.id)
    authors = db.execute(
        select(Image.author, image_count)
        .where(Image.author.is_not(None), Image.author != "")
        .group_by(Image.author)
        .order_by(image_count.desc())
    ).all()

    tagged_images = func.count(func.distinct(Tag.image_id))
    tags_by_category: dict[str, list[dict]] = {}
    for category, value, count in db.execute(
        select(Tag.category, Tag.value, tagged_images)
        .join(Image, Image.id == Tag.image_id)
        .group_by(Tag.category, Tag.value)
        .order_by(Tag.category, tagged_images.desc())
    ):
        tags_by_category.setdefault(category, []).append({"value": value, "count": count})

    grid = {"gridded": 0, "gridless": 0, "unknown": 0, "square": 0, "hex": 0}
    for gridded, grid_type, count in db.execute(
        select(Image.gridded, Image.grid_type, image_count).group_by(Image.gridded, Image.grid_type)
    ):
        if gridded is True:
            grid["gridded"] += count
            if grid_type in ("square", "hex"):
                grid[grid_type] += count
        elif gridded is False:
            grid["gridless"] += count
        else:
            grid["unknown"] += count

    coloured_images = func.count(func.distinct(Color.image_id))
    colors = db.execute(
        select(Color.color_hex, coloured_images)
        .join(Image, Image.id == Color.image_id)
        .group_by(Color.color_hex)
        .order_by(coloured_images.desc())
        .limit(50)
    ).all()

    image_types = db.execute(select(Image.image_type, image_count).group_by(Image.image_type)).all()
    media_types = db.execute(select(Image.media_type, image_count).group_by(Image.media_type)).all()

    return {
        "total_images": sum(count for _, count in image_types),
        "authors": [{"value": a, "count": c} for a, c in authors],
        "tags": tags_by_category,
        "gridded": grid,
        "colors": [{"hex": h, "count": c} for h, c in colors],
        "image_types": [{"value": t or "battlemap", "count": c} for t, c in image_types],
        "media_types": [{"value": m or "image", "count": c} for m, c in media_types],
    }
