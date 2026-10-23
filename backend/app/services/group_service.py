"""Changing gallery groups: minting them, moving images between them, merging and emptying
them.

Used by the groups API (the user's edits) and the import's grouping phase
(``backend/pipeline/group_jobs.py``, which mints groups). Moving images has the same side
effects everywhere:

- an image takes its new group's author, which is part of its search text, so the search
  text is rebuilt (the images' tags must be loaded);
- a group left without images is deleted;
- a group whose cover image left it gets another one.

Nothing here commits; callers own the transaction.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Sequence

from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session, selectinload

from ..models import Image, ImageGroup
from .fts_service import search_text_for
from .linked_files import chunks

# Minting


def mint_groups(db: Session, names: Sequence[tuple[str, str | None]]) -> list[int]:
    """New, empty gallery groups, one per (name, author); returns their ids in order. One
    batched ``INSERT .. RETURNING`` (thousands of groups for a large import). The import's
    grouping phase mints its groups with this (ADR-028); the caller puts images in them."""
    if not names:
        return []
    return list(
        db.scalars(
            insert(ImageGroup).returning(ImageGroup.id, sort_by_parameter_order=True),
            [{"base_name": name, "author": author} for name, author in names],
        )
    )


# Membership


def images_in_groups(db: Session, group_ids: Collection[int]) -> list[Image]:
    """The images of these groups, with their tags loaded (moving them rebuilds their
    search text, which includes the tags)."""
    images: list[Image] = []
    for chunk in chunks(sorted(set(group_ids))):
        images += (
            db.query(Image)
            .options(selectinload(Image.tags))
            .filter(Image.group_id.in_(chunk))
            .order_by(Image.id)
            .all()
        )
    return images


def reassign_images(images: Iterable[Image], target: ImageGroup) -> None:
    """Put images in ``target``. They take its author, which is part of their search text.
    The images' tags must be loaded."""
    for image in images:
        image.group_id = target.id
        image.author = target.author
        image.search_text = search_text_for(image)


def merge_groups(db: Session, target: ImageGroup, sources: Sequence[ImageGroup]) -> int:
    """Move every image of ``sources`` into ``target`` and delete the sources. Returns how
    many images moved. ``target`` keeps its name, author and cover."""
    sources = [s for s in sources if s.id != target.id]
    if not sources:
        return 0
    images = images_in_groups(db, [s.id for s in sources])
    reassign_images(images, target)
    # Flush so the session knows the images belong to target: otherwise deleting a
    # source would null their group_id through the relationship's bookkeeping.
    db.flush()
    for source in sources:
        db.delete(source)
    db.flush()
    return len(images)


def image_count(db: Session, group_id: int) -> int:
    """Images in the group now (this transaction's changes flushed)."""
    db.flush()
    return db.scalar(select(func.count(Image.id)).where(Image.group_id == group_id)) or 0


def delete_if_empty(db: Session, group: ImageGroup) -> bool:
    """Delete ``group`` if no image is left in it. Returns whether it was deleted."""
    if image_count(db, group.id):
        return False
    db.delete(group)
    db.flush()
    return True


def repair_cover(db: Session, group: ImageGroup) -> None:
    """Give ``group`` another cover if its cover image left it: its first remaining image,
    or none if it is empty."""
    if group.primary_image_id is None:
        return
    db.flush()
    still_here = db.scalar(
        select(Image.id).where(Image.id == group.primary_image_id, Image.group_id == group.id)
    )
    if still_here is None:
        group.primary_image_id = db.scalar(
            select(func.min(Image.id)).where(Image.group_id == group.id)
        )
