"""A set of images named by their groups and a filter, resolved on the server.

The group editor's bulk panel works on imports too large to hold in the browser (tens of
thousands of images), so it names what it means ("every image in these groups", "the
gridless ones", "those tagged night") and the server counts and resolves it.

Grid states match the editor's file filter (``frontend/src/components/import/fileFilter.ts``):
square and hex are gridded images of that grid type, gridded is any gridded image,
gridless is ``gridded = false``, unknown is ``gridded is null``.
"""

from typing import Any

from sqlalchemy import ColumnElement, and_, case, func, select
from sqlalchemy.orm import Session

from ..models import Image, Tag
from ..models.schemas import ImageScope, ImageScopeFacets, ImageScopeFilter, ScopeFacetCount

# Subgroups and tags listed in the facets, most common first.
FACET_LIMIT = 50


def _grid_condition(grid: str) -> ColumnElement[bool]:
    if grid in ("square", "hex"):
        return and_(Image.gridded.is_(True), Image.grid_type == grid)
    if grid == "gridded":
        return Image.gridded.is_(True)
    if grid == "gridless":
        return Image.gridded.is_(False)
    return Image.gridded.is_(None)


def _filter_conditions(flt: ImageScopeFilter) -> list[ColumnElement[bool]]:
    set_fields = flt.model_fields_set
    conditions: list[ColumnElement[bool]] = []
    if flt.image_type is not None:
        conditions.append(Image.image_type == flt.image_type)
    if flt.grid is not None:
        conditions.append(_grid_condition(flt.grid))
    if "subgroup" in set_fields:
        # Sent as null: images without a subgroup
        conditions.append(
            Image.subgroup.is_(None) if flt.subgroup is None else Image.subgroup == flt.subgroup
        )
    if flt.tag is not None:
        conditions.append(
            select(Tag.id)
            .where(
                Tag.image_id == Image.id,
                Tag.category == flt.tag.category,
                Tag.value == flt.tag.value,
            )
            .exists()
        )
    return conditions


def scope_conditions(scope: ImageScope) -> list[ColumnElement[bool]]:
    """WHERE conditions on ``Image`` selecting the scope's images."""
    return [Image.group_id.in_(scope.group_ids), *_filter_conditions(scope.filter)]


def resolve_scope(db: Session, scope: ImageScope) -> list[int]:
    """The ids of the scope's images, in id order."""
    return list(db.scalars(select(Image.id).where(*scope_conditions(scope)).order_by(Image.id)))


def _merged(rows: Any) -> list[tuple[str, int]]:
    """Sum counts by value (an unset type counts as a battlemap, like the editor shows it)."""
    totals: dict[str, int] = {}
    for value, n in rows:
        totals[value] = totals.get(value, 0) + n
    return sorted(totals.items(), key=lambda item: -item[1])


def _counts(rows: Any) -> list[ScopeFacetCount]:
    return [ScopeFacetCount(value=value, count=count) for value, count in rows]


def scope_facets(db: Session, scope: ImageScope) -> ImageScopeFacets:
    """Counts of the scope's images: in total, and by type, grid state, subgroup and tag."""
    where = scope_conditions(scope)
    total = db.scalar(select(func.count(Image.id)).where(*where)) or 0

    by_type = db.execute(
        select(Image.image_type, func.count(Image.id)).where(*where).group_by(Image.image_type)
    ).all()

    states = ("square", "hex", "gridded", "gridless", "unknown")
    grid_row = db.execute(
        select(*[func.sum(case((_grid_condition(s), 1), else_=0)) for s in states]).where(*where)
    ).one()
    grid = [ScopeFacetCount(value=s, count=n or 0) for s, n in zip(states, grid_row, strict=True)]

    count = func.count(Image.id).label("n")
    subgroups = db.execute(
        select(Image.subgroup, count)
        .where(*where)
        .group_by(Image.subgroup)
        .order_by(count.desc(), Image.subgroup)
        .limit(FACET_LIMIT)
    ).all()

    tag_count = func.count(Tag.id).label("n")
    tags = db.execute(
        select(Tag.category, Tag.value, tag_count)
        .join(Image, Image.id == Tag.image_id)
        .where(*where)
        .group_by(Tag.category, Tag.value)
        .order_by(tag_count.desc(), Tag.category, Tag.value)
        .limit(FACET_LIMIT)
    ).all()

    return ImageScopeFacets(
        total=total,
        image_type=_counts(_merged((t or "battlemap", n) for t, n in by_type)),
        grid=grid,
        subgroup=_counts(subgroups),
        tags=[ScopeFacetCount(value=f"{category}:{value}", count=n) for category, value, n in tags],
    )
