"""Edit many images at once, and put them back.

The group editor's bulk actions (add a tag, set the grid, type or subgroup) used to
re-save every affected group with ``PUT /groups/{id}``. These apply one change to any
number of images in a single transaction, with the same side effects as the
single-image endpoints:

- a changed grid field marks the grid as the user's (``grid_source``) and drops the
  detector's confidence, as ``PATCH /images/{id}`` does;
- setting ``gridded`` to False clears the grid fields the change doesn't set;
- tags and subgroup feed ``search_text``, so it's rebuilt for the images they touch.

Each edit returns the images' previous state, which ``restore_images`` accepts back:
that is the editor's undo.
"""

from collections.abc import Iterator, Sequence
from typing import Any

from sqlalchemy import delete, insert, select, update
from sqlalchemy.orm import Session, selectinload

from ..models import Image, ImageGroup, Tag
from ..models.database import GRID_FIELDS, GRID_SOURCE_USER
from ..models.schemas import ImageRestoreState, TagCreate
from .image_parser import build_search_text

# Restorable fields: everything a bulk edit can change, plus what a grid change
# overwrites as a side effect.
_RESTORED_FIELDS = (
    "image_type",
    "subgroup",
    *GRID_FIELDS,
    "grid_source",
    "grid_confidence",
)

# Ids per IN (...) query, well under SQLite's bound-parameter limit.
_CHUNK = 900


def _chunks(ids: Sequence[int]) -> Iterator[Sequence[int]]:
    for i in range(0, len(ids), _CHUNK):
        yield ids[i : i + _CHUNK]


def _load_images(db: Session, ids: Sequence[int]) -> list[Image]:
    unique = list(dict.fromkeys(ids))
    images: list[Image] = []
    for chunk in _chunks(unique):
        images += (
            db.query(Image).options(selectinload(Image.tags)).filter(Image.id.in_(chunk)).all()
        )
    return images


def _snapshot(image: Image) -> ImageRestoreState:
    return ImageRestoreState(id=image.id, **{f: getattr(image, f) for f in _RESTORED_FIELDS})


def _with_cleared_grid(changes: dict[str, Any]) -> dict[str, Any]:
    """Turning the grid off clears the grid fields the change doesn't set itself."""
    if changes.get("gridded") is not False:
        return changes
    return {**dict.fromkeys(GRID_FIELDS), **changes}


def _search_text(
    image: Image,
    tags: Sequence[tuple[str, str]],
    subgroup: str | None,
    author: str | None = None,
) -> str:
    return build_search_text(
        name=image.name,
        filename=image.filename,
        author=author if author is not None else image.author,
        tags=[{"category": c, "value": v} for c, v in tags],
        subgroup=subgroup,
    )


def _update_rows(db: Session, rows: list[dict[str, Any]]) -> None:
    """UPDATE images by primary key as executemany batches, not a statement per image.
    Rows are batched while they set the same columns, so give them all the same keys.

    ORM objects already loaded are left stale; callers return before reading them.
    """
    if rows:
        db.execute(update(Image), rows)


def _new_tags(image: Image, tags: Sequence[TagCreate]) -> list[TagCreate]:
    existing = {(t.category, t.value) for t in image.tags}
    return [t for t in tags if (t.category, t.value) not in existing]


def _edit_row(
    image: Image, changes: dict[str, Any], new_tags: Sequence[TagCreate] | None
) -> dict[str, Any]:
    """The UPDATE row for one image. ``new_tags`` is None when search text needn't change."""
    # Every row sets the same columns, so the UPDATE runs as one executemany
    row: dict[str, Any] = {
        "id": image.id,
        **changes,
        "grid_source": image.grid_source,
        "grid_confidence": image.grid_confidence,
    }
    if any(f in changes and changes[f] != getattr(image, f) for f in GRID_FIELDS):
        row |= {"grid_source": GRID_SOURCE_USER, "grid_confidence": None}
    if new_tags is not None:
        tags = [(t.category, t.value) for t in image.tags] + [
            (t.category, t.value) for t in new_tags
        ]
        row["search_text"] = _search_text(image, tags, row.get("subgroup", image.subgroup))
    return row


def bulk_edit_images(
    db: Session,
    image_ids: Sequence[int],
    changes: dict[str, Any],
    add_tags: Sequence[TagCreate],
) -> tuple[list[ImageRestoreState], list[int]]:
    """Apply ``changes`` and ``add_tags`` to every image in ``image_ids``.

    Returns each image's state from before the edit and the ids of the tags it added
    (tags an image already had aren't added again). Unknown ids are skipped. The
    caller commits.
    """
    changes = _with_cleared_grid(changes)
    reindex = bool(add_tags) or "subgroup" in changes
    images = _load_images(db, image_ids)
    previous = [_snapshot(image) for image in images]
    rows: list[dict[str, Any]] = []
    tag_rows: list[dict[str, Any]] = []
    for image in images:
        new = _new_tags(image, add_tags)
        tag_rows += [{"image_id": image.id, **t.model_dump()} for t in new]
        rows.append(_edit_row(image, changes, new if reindex else None))
    added_ids = list(db.scalars(insert(Tag).returning(Tag.id), tag_rows)) if tag_rows else []
    _update_rows(db, rows)
    return previous, added_ids


def restore_images(
    db: Session,
    states: Sequence[ImageRestoreState],
    remove_tag_ids: Sequence[int],
) -> int:
    """Put images back to ``states`` and drop the tags ``remove_tag_ids`` (an undo).

    Only tags belonging to the restored images are removed. Returns how many images
    were restored. The caller commits.
    """
    by_id = {s.id: s for s in states}
    images = _load_images(db, list(by_id))
    removing = set(remove_tag_ids)
    rows: list[dict[str, Any]] = []
    doomed: list[int] = []
    for image in images:
        state = by_id[image.id]
        kept = [t for t in image.tags if t.id not in removing]
        doomed += [t.id for t in image.tags if t.id in removing]
        tags = [(t.category, t.value) for t in kept]
        rows.append(
            {
                "id": image.id,
                **state.model_dump(exclude={"id"}),
                "search_text": _search_text(image, tags, state.subgroup),
            }
        )
    for chunk in _chunks(doomed):
        db.execute(delete(Tag).where(Tag.id.in_(chunk)))
    _update_rows(db, rows)
    return len(images)


def set_groups_author(db: Session, group_ids: Sequence[int], author: str | None) -> int:
    """Set the author of many groups and of their images, as ``PUT /groups/{id}`` does
    for one (images carry their group's author, and it's part of their search text).

    Returns how many groups were updated; unknown ids are skipped. The caller commits.
    """
    unique = list(dict.fromkeys(group_ids))
    found: list[int] = []
    rows: list[dict[str, Any]] = []
    for chunk in _chunks(unique):
        found += db.scalars(select(ImageGroup.id).where(ImageGroup.id.in_(chunk))).all()
        images = (
            db.query(Image)
            .options(selectinload(Image.tags))
            .filter(Image.group_id.in_(chunk))
            .all()
        )
        rows += [
            {
                "id": image.id,
                "author": author,
                "search_text": _search_text(
                    image, [(t.category, t.value) for t in image.tags], image.subgroup, author or ""
                ),
            }
            for image in images
        ]
    if found:
        db.execute(update(ImageGroup), [{"id": gid, "author": author} for gid in found])
    _update_rows(db, rows)
    return len(found)
