"""Edit many images at once, and put them back.

The group editor's bulk actions (add a tag, set the grid, type or subgroup) used to
re-save every affected group with ``PUT /groups/{id}``. These apply one change to any
number of images in a single transaction, with the same side effects as the
single-image endpoints:

- a changed grid field marks the grid as the user's (``grid_source``) and drops the
  detector's confidence, as ``PATCH /images/{id}`` does;
- setting ``gridded`` to False clears the grid fields the change doesn't set;
- tags and subgroup feed ``search_text``, so it's rebuilt for the images they touch.

Each edit returns an ``UndoRecord`` (the images' previous state and the tags it added),
which ``restore_images`` puts back: the editor's undo. A 50k-image edit's record is several
MB, so it stays on the server: ``remember_undo`` keeps the last few in memory under an id.
They're lost on restart, which only means that Undo stops working.
"""

import threading
import uuid
from collections import OrderedDict
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import ColumnElement, delete, insert, select, update
from sqlalchemy.orm import Session

from ..models import Image, ImageGroup, Tag
from ..models.database import GRID_FIELDS, GRID_SOURCE_USER
from ..models.schemas import TagCreate
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


@dataclass
class _TagRow:
    id: int
    category: str
    value: str


@dataclass
class _ImageRow:
    """The columns a bulk edit reads, as a plain row: building ORM objects (and their
    tags) for 50k images was most of a whole-import edit's time."""

    id: int
    name: str | None
    filename: str
    author: str | None
    image_type: str | None
    subgroup: str | None
    gridded: bool | None
    grid_width: int | None
    grid_height: int | None
    grid_type: str | None
    grid_source: str | None
    grid_confidence: float | None
    tags: list[_TagRow] = field(default_factory=list)


_IMAGE_COLUMNS = (
    Image.id,
    Image.name,
    Image.filename,
    Image.author,
    Image.image_type,
    Image.subgroup.label("subgroup"),
    Image.gridded,
    Image.grid_width,
    Image.grid_height,
    Image.grid_type,
    Image.grid_source,
    Image.grid_confidence,
)


def _rows_where(db: Session, condition: ColumnElement[bool]) -> list[_ImageRow]:
    """The images matching ``condition``, with their tags: two queries."""
    images = {
        row.id: _ImageRow(**row._mapping)
        for row in db.execute(select(*_IMAGE_COLUMNS).where(condition))
    }
    tags = db.execute(
        select(Tag.image_id, Tag.id, Tag.category, Tag.value).where(
            Tag.image_id.in_(select(Image.id).where(condition))
        )
    )
    for image_id, tag_id, category, value in tags:
        images[image_id].tags.append(_TagRow(tag_id, category, value))
    return list(images.values())


def _load_images(db: Session, ids: Sequence[int]) -> list[_ImageRow]:
    unique = list(dict.fromkeys(ids))
    images: list[_ImageRow] = []
    for chunk in _chunks(unique):
        images += _rows_where(db, Image.id.in_(chunk))
    return images


@dataclass(frozen=True)
class UndoRecord:
    """What undoing a bulk edit needs: each image's previous restorable fields (in
    ``_RESTORED_FIELDS`` order, keyed by id) and the ids of the tags the edit added."""

    previous: dict[int, tuple[Any, ...]]
    added_tag_ids: list[int]


# Recent edits that can still be undone, oldest first.
_UNDO_KEEP = 5
_undo_records: OrderedDict[str, UndoRecord] = OrderedDict()
_undo_lock = threading.Lock()


def remember_undo(record: UndoRecord) -> str:
    """Keep ``record`` for undo (only the last few are kept); returns its id."""
    undo_id = uuid.uuid4().hex
    with _undo_lock:
        _undo_records[undo_id] = record
        while len(_undo_records) > _UNDO_KEEP:
            _undo_records.popitem(last=False)
    return undo_id


def undo_record(undo_id: str) -> UndoRecord | None:
    with _undo_lock:
        return _undo_records.get(undo_id)


def forget_undo(undo_id: str) -> None:
    with _undo_lock:
        _undo_records.pop(undo_id, None)


def _snapshot(image: _ImageRow) -> tuple[Any, ...]:
    return tuple(getattr(image, f) for f in _RESTORED_FIELDS)


def _with_cleared_grid(changes: dict[str, Any]) -> dict[str, Any]:
    """Turning the grid off clears the grid fields the change doesn't set itself."""
    if changes.get("gridded") is not False:
        return changes
    return {**dict.fromkeys(GRID_FIELDS), **changes}


def _search_text(
    image: _ImageRow,
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

    """
    if rows:
        db.execute(update(Image), rows)


def _new_tags(image: _ImageRow, tags: Sequence[TagCreate]) -> list[TagCreate]:
    existing = {(t.category, t.value) for t in image.tags}
    return [t for t in tags if (t.category, t.value) not in existing]


def _edit_row(
    image: _ImageRow, changes: dict[str, Any], new_tags: Sequence[TagCreate] | None
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
) -> tuple[int, UndoRecord]:
    """Apply ``changes`` and ``add_tags`` to every image in ``image_ids``.

    Returns how many images were edited (unknown ids are skipped), and what undoing it
    needs. Tags an image already had aren't added again. The caller commits, then
    ``remember_undo``.
    """
    changes = _with_cleared_grid(changes)
    reindex = bool(add_tags) or "subgroup" in changes
    images = _load_images(db, image_ids)
    previous = {image.id: _snapshot(image) for image in images}
    rows: list[dict[str, Any]] = []
    tag_rows: list[dict[str, Any]] = []
    for image in images:
        new = _new_tags(image, add_tags)
        tag_rows += [{"image_id": image.id, **t.model_dump()} for t in new]
        rows.append(_edit_row(image, changes, new if reindex else None))
    added_ids = list(db.scalars(insert(Tag).returning(Tag.id), tag_rows)) if tag_rows else []
    _update_rows(db, rows)
    return len(images), UndoRecord(previous, added_ids)


def restore_images(db: Session, record: UndoRecord) -> int:
    """Undo a bulk edit: put its images' fields back and drop the tags it added.

    Returns how many images were restored (images deleted since are skipped). The caller
    commits.
    """
    images = _load_images(db, list(record.previous))
    removing = set(record.added_tag_ids)
    rows: list[dict[str, Any]] = []
    doomed: list[int] = []
    for image in images:
        state = dict(zip(_RESTORED_FIELDS, record.previous[image.id], strict=True))
        doomed += [t.id for t in image.tags if t.id in removing]
        tags = [(t.category, t.value) for t in image.tags if t.id not in removing]
        rows.append(
            {
                "id": image.id,
                **state,
                "search_text": _search_text(image, tags, state["subgroup"]),
            }
        )
    for chunk in _chunks(doomed):
        # No session sync: with every image's tags loaded, the default "evaluate" tests
        # each loaded Tag against the IN list, which took ~60 s for a 50k-image undo
        db.execute(
            delete(Tag).where(Tag.id.in_(chunk)).execution_options(synchronize_session=False)
        )
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
        images = _rows_where(db, Image.group_id.in_(chunk))
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
