"""The linked folder's rows: ``library_sources`` and ``source_files`` (design/library-setup.md §4).

A ``source_files`` row records what became of one file in the linked folder, so a
rescan never reads a file it has already seen. This module keeps the rows in step with
everything that happens to their files and images:

- ``sync_files``: an import item's outcome is written back to its file (§4.4);
- ``move_if_missing``: a file whose bytes are a linked image whose own file is missing
  is that image's file, moved: the image is repointed to it (§4.4);
- ``forget_images``: removing an image marks its file ``removed``, so rescans leave it
  out (§4.6);
- ``remove_images``: "Remove missing maps" and "Unlink" (§4.7).

The rows never reach the disk; reading a file is ``services.originals``' job. No
function here commits: callers own the transaction.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from ..models import Image, ImageGroup, ImportItem, ImportJob, LibrarySource, SourceFile
from ..models.database import (
    FILE_DUPLICATE,
    FILE_FAILED,
    FILE_IMAGE,
    FILE_PENDING,
    FILE_REMOVED,
    FILE_SKIPPED,
    SOURCE_DETACHED,
    SOURCE_KIND_FOLDER,
)
from . import ingest_state as st

logger = logging.getLogger(__name__)

_CHUNK = 500  # far below SQLite's bound-variable limit

# Skipped items whose files stay ``skipped``: Auto sorted them out. Other skips (Cancel,
# skipping a group) forget the file, so the next scan offers it again.
_SORTED_OUT_KINDS = frozenset({"sorted_out", "sorted_out_expired"})

# (size, mtime_ns) of a file as it was read
Version = tuple[int, int]


def chunks[T](values: list[T], size: int = _CHUNK) -> Iterable[list[T]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def files_by_id(db: Session, file_ids: list[int]) -> dict[int, SourceFile]:
    return {
        row.id: row
        for chunk in chunks(file_ids)
        for row in db.query(SourceFile).filter(SourceFile.id.in_(chunk))
    }


# The source


def current_source(db: Session) -> LibrarySource | None:
    """The linked folder's row (there is at most one)."""
    return db.query(LibrarySource).order_by(LibrarySource.id).first()


def ensure_source(db: Session, location: str) -> LibrarySource:
    """The source row for the configured folder, created on first use. A different
    last-known location is updated: files are matched by relative path, so a folder
    under a new drive letter just works."""
    source = current_source(db)
    if source is None:
        source = LibrarySource(kind=SOURCE_KIND_FOLDER, location=location)
        db.add(source)
        db.flush()
    elif source.location != location:
        logger.info("Linked folder moved: %s -> %s", source.location, location)
        source.location = location
    return source


# Item outcomes (§4.4)


def sync_files(
    db: Session, items: Iterable[ImportItem], versions: dict[int, Version] | None = None
) -> None:
    """Write linked items' states back to their files. ``versions``: item id → the
    (size, mtime) the item was read at, recorded so a rescan sees the file unchanged.

    - done → ``image``; duplicate → ``duplicate`` (with the image it matches);
    - skipped by Auto → ``skipped`` with the reason; skipped otherwise (Cancel, a skipped
      group) → the row is deleted, so the next scan offers the file again;
    - failed → ``failed`` with the reason; open again (Retry, Include) → ``pending``;
    - a file that already is an image's (a refresh, §4.5) stays the image's: see
      ``_sync_refresh``.

    A byte duplicate of a linked image whose own file is missing is that file, moved
    (``move_if_missing``).
    """
    linked = [(item, item.source_file_id) for item in items if item.source_file_id is not None]
    if not linked:
        return
    rows = files_by_id(db, [file_id for _, file_id in linked])
    versions = versions or {}
    forgotten: list[int] = []
    for item, file_id in linked:
        row = rows.get(file_id)
        if row is None or row.state == FILE_REMOVED:
            continue
        if not _sync_file(row, item, versions.get(item.id)):
            forgotten.append(row.id)
    delete_files(db, forgotten)
    for item, file_id in linked:
        if (image_id := _byte_duplicate_of(item)) is not None:
            move_if_missing(db, image_id, file_id)


# The file row (state, image, reason) an item's state settles into
_Outcome = tuple[str, int | None, str | None]


def _outcome(item: ImportItem) -> _Outcome | None:
    """None: the file is forgotten, so the next scan offers it again."""
    if item.state == st.DONE:
        return FILE_IMAGE, item.image_id, None
    if item.state == st.DUPLICATE:
        return FILE_DUPLICATE, item.duplicate_of_image_id, None
    if item.state == st.SKIPPED:
        if item.error_kind in _SORTED_OUT_KINDS:
            return FILE_SKIPPED, None, item.error_reason
        return None
    if item.state == st.FAILED:
        return FILE_FAILED, None, item.error_reason
    return FILE_PENDING, None, None  # open again


def _sync_file(row: SourceFile, item: ImportItem, version: Version | None) -> bool:
    """Write one item's state back to its file. Returns False if the row is to be deleted."""
    if row.state == FILE_IMAGE:
        _sync_refresh(row, item, version)
        return True
    if version is not None:
        row.size, row.mtime_ns = version
    if item.source_hash:
        row.content_hash = item.source_hash
    outcome = _outcome(item)
    if outcome is None:
        return False
    row.state, row.image_id, row.reason = outcome
    return True


def _byte_duplicate_of(item: ImportItem) -> int | None:
    """The image whose bytes the item's file has, if it's a byte duplicate."""
    if item.state == st.DUPLICATE and item.duplicate_tier == "bytes":
        return item.duplicate_of_image_id
    return None


def _sync_refresh(row: SourceFile, item: ImportItem, version: Version | None) -> None:
    """A file that already is an image's: its item was a refresh (§4.5), and the row stays
    the image's whatever became of the item. Done records the version read and its hash;
    failed records the version that failed (a rescan reads it again once it changes) and
    why. Anything else (Cancel, Retry, recovery) leaves the row as it was, so a rescan
    still sees the file as changed and offers it again."""
    if item.state not in (st.DONE, st.FAILED):
        return
    if version is not None:
        row.size, row.mtime_ns = version
    if item.state == st.DONE:
        if item.source_hash:
            row.content_hash = item.source_hash
        row.reason = None
    else:
        row.reason = item.error_reason


def delete_files(db: Session, file_ids: list[int]) -> None:
    """Delete file rows, and the references import items keep to them."""
    for chunk in chunks(file_ids):
        db.execute(
            update(ImportItem)
            .where(ImportItem.source_file_id.in_(chunk))
            .values(source_file_id=None)
        )
        db.execute(delete(SourceFile).where(SourceFile.id.in_(chunk)))


def move_if_missing(db: Session, image_id: int, file_id: int) -> bool:
    """A file whose bytes match a linked image whose own file is missing is that image's
    file, moved or renamed: repoint the image to it, keeping all its metadata, and delete
    the old row. Returns whether it was a move."""
    image = db.get(Image, image_id)
    if image is None or image.source_file_id is None or image.source_file_id == file_id:
        return False
    old = db.get(SourceFile, image.source_file_id)
    new = db.get(SourceFile, file_id)
    if new is None or (old is not None and old.missing_since is None):
        return False
    if new.state == FILE_IMAGE and new.image_id != image.id:
        return False  # already another image's file
    image.source_file_id = new.id
    new.state, new.image_id, new.reason, new.missing_since = FILE_IMAGE, image.id, None, None
    db.flush()
    if old is not None:
        delete_files(db, [old.id])
    logger.info("Linked image %s moved to %s", image.id, new.rel_key)
    return True


def repoint_to_duplicates(db: Session, source_id: int) -> int:
    """Images whose file is missing take over a present duplicate of it, if one was
    found earlier (§4.4: "duplicates, and moves"). Returns how many were repointed."""
    missing = (
        select(SourceFile.id, SourceFile.image_id)
        .where(
            SourceFile.source_id == source_id,
            SourceFile.state == FILE_IMAGE,
            SourceFile.missing_since.isnot(None),
        )
        .subquery()
    )
    rows = db.execute(
        select(SourceFile.id, SourceFile.image_id)
        .join(missing, missing.c.image_id == SourceFile.image_id)
        .where(SourceFile.state == FILE_DUPLICATE, SourceFile.missing_since.is_(None))
        .order_by(SourceFile.id)
    ).all()
    moved = 0
    seen: set[int] = set()
    for file_id, image_id in rows:
        if image_id is None or image_id in seen:
            continue
        seen.add(image_id)
        moved += move_if_missing(db, image_id, file_id)
    return moved


# Removing images (§4.6)


def forget_images(db: Session, images: list[Image]) -> None:
    """Images are being deleted: their files become ``removed`` so rescans don't bring
    them back, and so do files recorded as their duplicates. Files are never touched."""
    image_ids = [image.id for image in images]
    file_ids = [image.source_file_id for image in images if image.source_file_id is not None]
    for chunk in chunks(file_ids):
        db.execute(
            update(SourceFile)
            .where(SourceFile.id.in_(chunk))
            .values(state=FILE_REMOVED, image_id=None, reason=None)
        )
    for chunk in chunks(image_ids):
        db.execute(
            update(SourceFile)
            .where(SourceFile.image_id.in_(chunk), SourceFile.state == FILE_DUPLICATE)
            .values(state=FILE_REMOVED, image_id=None)
        )


def missing_image_ids(db: Session, source_id: int) -> list[int]:
    return list(
        db.scalars(
            select(Image.id)
            .join(SourceFile, SourceFile.id == Image.source_file_id)
            .where(SourceFile.source_id == source_id, SourceFile.missing_since.isnot(None))
            .order_by(Image.id)
        )
    )


def linked_image_ids(db: Session, source_id: int) -> list[int]:
    return list(
        db.scalars(
            select(Image.id)
            .join(SourceFile, SourceFile.id == Image.source_file_id)
            .where(SourceFile.source_id == source_id)
            .order_by(Image.id)
        )
    )


def remove_images(db: Session, image_ids: list[int]):
    """Delete these images (rows now; thumbnails and vectors once the caller has committed
    and applied the returned ``PendingFileDeletes``), and the groups they leave empty.
    Their files become ``removed``; the files themselves are never touched."""
    from .deletion_service import PendingFileDeletes, delete_image_rows

    pending = PendingFileDeletes()
    group_ids: set[int] = set()
    for chunk in chunks(image_ids):
        images = db.query(Image).filter(Image.id.in_(chunk)).all()
        group_ids |= {image.group_id for image in images if image.group_id is not None}
        found = delete_image_rows(db, images)
        pending.storage_keys += found.storage_keys
        pending.thumbnail_keys += found.thumbnail_keys
        pending.image_ids += found.image_ids
    for chunk in chunks(image_ids):
        db.execute(
            update(ImageGroup)
            .where(ImageGroup.primary_image_id.in_(chunk))
            .values(primary_image_id=None)
        )
    groups = sorted(group_ids)
    for chunk in chunks(groups):
        still_used = select(Image.group_id).where(Image.group_id.in_(chunk))
        db.execute(
            delete(ImageGroup).where(ImageGroup.id.in_(chunk), ImageGroup.id.not_in(still_used))
        )
    return pending


def detach_source(db: Session, source: LibrarySource) -> None:
    """The source's folder is no longer used: forget its files and mark it detached."""
    file_ids = list(db.scalars(select(SourceFile.id).where(SourceFile.source_id == source.id)))
    delete_files(db, file_ids)
    source.state = SOURCE_DETACHED


# Linked jobs


def open_linked_jobs(db: Session, source_id: int) -> list[ImportJob]:
    return (
        db.query(ImportJob)
        .filter(
            ImportJob.library_source_id == source_id,
            ImportJob.status.in_((st.JOB_ACTIVE, st.JOB_PAUSED)),
        )
        .all()
    )


def linked_jobs_busy(db: Session, source_id: int) -> bool:
    """Whether a batch of the source's items is being processed right now."""
    return bool(
        db.query(ImportItem.id)
        .join(ImportJob, ImportJob.id == ImportItem.job_id)
        .filter(ImportJob.library_source_id == source_id, ImportItem.state == st.PROCESSING)
        .first()
    )


def count_linked(db: Session, source_id: int) -> tuple[int, int]:
    """(images read from the source, of them with a missing file)."""
    images = db.scalar(
        select(func.count(Image.id))
        .join(SourceFile, SourceFile.id == Image.source_file_id)
        .where(SourceFile.source_id == source_id)
    )
    missing = db.scalar(
        select(func.count(SourceFile.id)).where(
            SourceFile.source_id == source_id,
            SourceFile.state == FILE_IMAGE,
            SourceFile.missing_since.isnot(None),
        )
    )
    return images or 0, missing or 0
