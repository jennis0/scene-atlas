"""The linked folder's rows kept in step with items and images
(backend/app/services/linked_files.py, design/library-setup.md §4.4, §4.6)."""

from __future__ import annotations

from datetime import datetime

import pytest

from backend.app.models import Image, ImportItem, ImportJob, LibrarySource, SourceFile
from backend.app.models.database import (
    FILE_DUPLICATE,
    FILE_FAILED,
    FILE_IMAGE,
    FILE_PENDING,
    FILE_REMOVED,
    FILE_SKIPPED,
)
from backend.app.services import ingest_state as st
from backend.app.services.linked_files import (
    forget_images,
    move_if_missing,
    repoint_to_duplicates,
    sync_files,
)


@pytest.fixture
def source(db_session) -> LibrarySource:
    source = LibrarySource(kind="folder", location="/maps", state="online")
    db_session.add(source)
    db_session.add(ImportJob(id="job", status="active"))
    db_session.flush()
    return source


def add_file(db, source, key: str, state=FILE_PENDING, **kw) -> SourceFile:
    row = SourceFile(source_id=source.id, rel_key=key, size=1, mtime_ns=1, state=state, **kw)
    db.add(row)
    db.flush()
    return row


def add_image(db, row: SourceFile | None = None, **kw) -> Image:
    image = Image(
        filename="map.png",
        storage_key=None if row is not None else "stored.png",
        source_file_id=row.id if row is not None else None,
        **kw,
    )
    db.add(image)
    db.flush()
    if row is not None:
        row.state, row.image_id = FILE_IMAGE, image.id
    return image


def add_item(db, row: SourceFile, state: str, **kw) -> ImportItem:
    item = ImportItem(
        job_id="job",
        relative_path=row.rel_key,
        filename="map.png",
        state=state,
        source_file_id=row.id,
        **kw,
    )
    db.add(item)
    db.flush()
    return item


# ---------------------------------------------------------------------------
# sync_files: item outcomes are written back
# ---------------------------------------------------------------------------


def test_outcomes_are_written_back(db_session, source):
    db = db_session
    image = add_image(db)
    rows = {key: add_file(db, source, key) for key in "abcdef"}
    items = [
        add_item(db, rows["a"], st.DONE, image_id=image.id, source_hash="h" * 64),
        add_item(db, rows["b"], st.DUPLICATE, duplicate_of_image_id=image.id),
        add_item(db, rows["c"], st.SKIPPED, error_kind="sorted_out", error_reason="Token"),
        add_item(db, rows["d"], st.FAILED, error_reason="Broken"),
        add_item(db, rows["e"], st.READY),
        add_item(db, rows["f"], st.SKIPPED, error_reason="Cancelled"),
    ]
    sync_files(db, items, {items[0].id: (42, 4242)})
    db.flush()
    db.expire_all()

    found = {row.rel_key: row for row in db.query(SourceFile)}
    assert (found["a"].state, found["a"].image_id) == (FILE_IMAGE, image.id)
    assert (found["a"].size, found["a"].mtime_ns, found["a"].content_hash) == (42, 4242, "h" * 64)
    assert (found["b"].state, found["b"].image_id) == (FILE_DUPLICATE, image.id)
    assert (found["c"].state, found["c"].reason) == (FILE_SKIPPED, "Token")
    assert (found["d"].state, found["d"].reason) == (FILE_FAILED, "Broken")
    assert found["e"].state == FILE_PENDING
    # Cancelled: forgotten, so the next scan offers the file again
    assert "f" not in found
    assert db.get(ImportItem, items[5].id).source_file_id is None  # pyright: ignore[reportOptionalMemberAccess]


@pytest.mark.parametrize(
    ("state", "kw", "expected"),
    [
        # Refreshed: the version read and its hash
        (st.DONE, {"source_hash": "n" * 64}, ((42, 4242), "n" * 64, None)),
        # Failed: the version that failed and why; the image keeps its old bytes' hash
        (st.FAILED, {"error_reason": "Broken"}, ((42, 4242), "o" * 64, "Broken")),
        # Cancelled, retried, recovered: untouched, so a rescan offers it again
        (st.SKIPPED, {"error_reason": "Cancelled"}, ((1, 1), "o" * 64, None)),
        (st.READY, {}, ((1, 1), "o" * 64, None)),
    ],
)
def test_a_refresh_never_takes_the_file_from_its_image(db_session, source, state, kw, expected):
    """§4.5: an image's file stays the image's whatever its refresh item became."""
    db = db_session
    row = add_file(db, source, "A/map.png", content_hash="o" * 64)
    image = add_image(db, row)
    item = add_item(db, row, state, **kw)
    sync_files(db, [item], {item.id: (42, 4242)})
    db.flush()
    db.expire_all()

    found = db.get(SourceFile, row.id)
    assert found is not None
    assert (found.state, found.image_id) == (FILE_IMAGE, image.id)
    assert ((found.size, found.mtime_ns), found.content_hash, found.reason) == expected


def test_items_without_a_file_are_left_alone(db_session, source):
    item = ImportItem(job_id="job", relative_path="x.png", filename="x.png", state=st.DONE)
    db_session.add(item)
    db_session.flush()
    sync_files(db_session, [item])  # nothing to do, nothing raised


# ---------------------------------------------------------------------------
# Moves: a missing image takes the file that has its bytes
# ---------------------------------------------------------------------------


def test_a_missing_image_moves_to_its_file(db_session, source):
    db = db_session
    old = add_file(db, source, "Old/map.png", missing_since=datetime(2026, 1, 1))
    image = add_image(db, old)
    new = add_file(db, source, "New/map.png", state=FILE_DUPLICATE, image_id=image.id)

    assert move_if_missing(db, image.id, new.id)
    db.flush()
    assert image.source_file_id == new.id
    assert (new.state, new.image_id) == (FILE_IMAGE, image.id)
    assert db.get(SourceFile, old.id) is None


def test_a_present_image_is_not_moved(db_session, source):
    db = db_session
    present = add_file(db, source, "A/map.png")
    image = add_image(db, present)
    copy = add_file(db, source, "B/map.png", state=FILE_DUPLICATE, image_id=image.id)
    assert not move_if_missing(db, image.id, copy.id)
    assert image.source_file_id == present.id
    # Nor is a stored image
    stored = add_image(db)
    assert not move_if_missing(db, stored.id, copy.id)


def test_duplicates_take_over_on_a_rescan(db_session, source):
    db = db_session
    gone = add_file(db, source, "A/map.png", missing_since=datetime(2026, 1, 1))
    image = add_image(db, gone)
    copy = add_file(db, source, "B/map.png", state=FILE_DUPLICATE, image_id=image.id)
    # A duplicate that's missing too can't take over
    add_file(
        db,
        source,
        "C/map.png",
        state=FILE_DUPLICATE,
        image_id=image.id,
        missing_since=datetime(2026, 1, 1),
    )
    db.flush()
    assert repoint_to_duplicates(db, source.id) == 1
    assert image.source_file_id == copy.id


# ---------------------------------------------------------------------------
# Removing images
# ---------------------------------------------------------------------------


def test_removing_an_image_marks_its_files_removed(db_session, source):
    db = db_session
    row = add_file(db, source, "A/map.png")
    image = add_image(db, row)
    copy = add_file(db, source, "B/map.png", state=FILE_DUPLICATE, image_id=image.id)
    stored = add_image(db)
    copy_of_stored = add_file(db, source, "C/map.png", state=FILE_DUPLICATE, image_id=stored.id)
    db.flush()

    forget_images(db, [image, stored])
    db.flush()
    db.expire_all()
    for file_id in (row.id, copy.id, copy_of_stored.id):
        found = db.get(SourceFile, file_id)
        assert found is not None
        assert (found.state, found.image_id) == (FILE_REMOVED, None)
