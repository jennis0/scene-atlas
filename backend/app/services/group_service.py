"""Changing gallery groups: moving images between them, merging and emptying them, and
recording that the user edited them.

Shared by the groups API (the user's edits) and by grouping refinement
(``backend/pipeline/refine_groups.py``, ADR-028), so both move images with the same side
effects:

- an image takes its new group's author, which is part of its search text, so the search
  text is rebuilt (the images' tags must be loaded);
- a group left without images is deleted;
- a group whose cover image left it gets another one.

**Provenance** (design/variant-grouping.md §6): every user edit of a group's metadata or
membership sets ``ImageGroup.edited_at`` (``mark_edited`` / ``mark_groups_edited``), and
automatic grouping never changes an edited group, as re-detection never changes a
``grid_source = user`` grid. Refinement itself doesn't mark the groups it merges: they are
still the importer's.

Nothing here commits; callers own the transaction.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Sequence

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, selectinload

from ..models import Image, ImageGroup
from ..timeutil import utcnow
from .fts_service import search_text_for
from .linked_files import chunks

# Provenance


def mark_edited(*groups: ImageGroup | None) -> None:
    """Record a user edit of these groups (None entries are ignored)."""
    now = utcnow()
    for group in groups:
        if group is not None:
            group.edited_at = now


def mark_groups_edited(db: Session, group_ids: Iterable[int | None]) -> None:
    """Record a user edit of the groups with these ids, without loading them. Unknown ids
    and None (an image without a group) are ignored."""
    ids = sorted({gid for gid in group_ids if gid is not None})
    now = utcnow()
    for chunk in chunks(ids):
        db.execute(
            update(ImageGroup)
            .where(ImageGroup.id.in_(chunk))
            .values(edited_at=now)
            .execution_options(synchronize_session=False)
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
