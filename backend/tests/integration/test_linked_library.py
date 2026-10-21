"""Integration tests for the linked library (design/library-setup.md §4, §5).

A real maps folder in tmp_path, scanned and processed through the real HTTP API,
SQLite, LanceDB and filesystem; embeddings are faked, scans run on the test's thread and
the worker is driven with ``drain()``. The test client runs in server mode, with the
folder set as ``LINKED_LIBRARY_DIR`` would set it.
"""

from __future__ import annotations

import hashlib
import os
import time
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import insert

from backend.app.config import settings
from backend.app.models import Image, ImportItem, ImportJob, LibrarySource, SourceFile, Tag
from backend.app.models.database import (
    FILE_DUPLICATE,
    FILE_IMAGE,
    FILE_PENDING,
    FILE_REMOVED,
    SOURCE_DETACHED,
    SOURCE_OFFLINE,
    SOURCE_ONLINE,
)
from backend.app.services import get_thumbnail_store, originals
from backend.app.services import ingest_state as st
from backend.pipeline import ingest_queue as q
from backend.pipeline import linked_scan, linked_scanner
from backend.pipeline.linked_refresh import REFRESH_GONE_REASON
from backend.pipeline.linked_scan import ScanResult, reconcile_linked_source
from backend.pipeline.linked_scanner import LinkedScanner

from .test_imports_api import BASE, image_bytes
from .test_local_ingest import library_files, tree_digest, write_tree

LIBRARY = "/api/v1/library"


class Linked:
    """The API with a linked folder at ``root``."""

    def __init__(self, api, root: Path):
        self.api = api
        self.client = api.client
        self.root = root

    def scan(self) -> ScanResult:
        result = linked_scanner.get_linked_scanner().scan()
        assert result is not None
        return result

    def sync(self) -> ScanResult:
        """Scan, then import what it found."""
        result = self.scan()
        self.api.worker.drain()
        originals.forget_availability()
        return result

    def images(self) -> dict[str | None, Image]:
        """Linked images by their file's key."""
        with self.api.SessionLocal() as db:
            rows = (
                db.query(Image, SourceFile.rel_key)
                .join(SourceFile, SourceFile.id == Image.source_file_id)
                .all()
            )
            for image, _ in rows:
                db.expunge(image)
            return {key: image for image, key in rows}

    def rows(self) -> dict[str | None, SourceFile]:
        with self.api.SessionLocal() as db:
            rows = db.query(SourceFile).all()
            for row in rows:
                db.expunge(row)
            return {row.rel_key: row for row in rows}

    def jobs(self) -> list[ImportJob]:
        with self.api.SessionLocal() as db:
            jobs = db.query(ImportJob).order_by(ImportJob.created_at).all()
            for job in jobs:
                db.expunge(job)
            return jobs

    def image(self, image_id: int) -> dict:
        r = self.client.get(f"/api/v1/images/{image_id}")
        assert r.status_code == 200, r.text
        return r.json()

    def status(self) -> dict:
        r = self.client.get(f"{LIBRARY}/status")
        assert r.status_code == 200, r.text
        return r.json()["linked"]


@pytest.fixture
def linked(api, tmp_path, monkeypatch):
    root = tmp_path / "Maps"
    root.mkdir()
    monkeypatch.setattr(settings, "linked_library_dir", root)
    monkeypatch.setattr(linked_scanner, "_scanner", LinkedScanner())
    monkeypatch.setattr(q, "SOURCE_CHANGED_DELAY", timedelta(0))
    originals.forget_availability()
    yield Linked(api, root)
    originals.forget_availability()


FOREST = {
    "Czepeku/Forest/Forest_Day.png": image_bytes(1),
    "Czepeku/Forest/Forest_Night.png": image_bytes(2),
    "Czepeku/Forest/notes.txt": b"not a map",
}


@pytest.fixture
def forest(linked):
    """The folder with one pack, scanned and imported."""
    write_tree(linked.root, FOREST)
    linked.sync()
    return linked


def touch(path: Path, mtime_ns: int) -> None:
    os.utime(path, ns=(mtime_ns, mtime_ns))


# The first scan


def test_first_scan_imports_the_folder_in_place(linked):
    write_tree(linked.root, FOREST)
    before = tree_digest(linked.root)

    result = linked.scan()
    assert (result.state, result.new) == ("online", 2)
    summary = next(j for j in linked.client.get(BASE).json()["jobs"] if j["id"] == result.job_id)
    assert summary["linked"] is True
    assert summary["label"] == "Maps"
    assert summary["default_image_type"] == "auto"

    linked.api.worker.drain()
    detail = linked.api.detail(result.job_id)
    assert detail["status"] == "completed" and detail["counts"]["done"] == 2

    images = linked.images()
    assert set(images) == {"Czepeku/Forest/Forest_Day.png", "Czepeku/Forest/Forest_Night.png"}
    for key, image in images.items():
        assert image.storage_key is None
        assert image.author == "Czepeku"  # keys are relative to the folder itself
        r = linked.client.get(f"/api/v1/images/{image.id}/file")
        assert r.status_code == 200 and r.content == FOREST[key]
        body = linked.image(image.id)
        assert body["file_state"] == "ok" and body["storage_key"] is None
        assert linked.client.get(f"/api/v1/images/{image.id}/thumbnail").status_code == 200
    rows = linked.rows()
    assert {row.state for row in rows.values()} == {FILE_IMAGE}
    assert all(row.content_hash for row in rows.values())

    assert library_files() == []  # nothing copied into the store
    assert tree_digest(linked.root) == before  # the folder is never written

    status = linked.status()
    assert status["state"] == "online" and status["name"] == "Maps"
    assert status["path"] is None  # server mode never shows the path
    assert (status["image_count"], status["missing_count"]) == (2, 0)
    assert status["last_scan_at"] is not None and status["scanning"] is False
    # Sent with its UTC offset, so browsers don't read it as local time
    assert status["last_scan_at"].endswith(("Z", "+00:00"))


def test_a_rescan_without_changes_reads_no_file(forest, monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("a file was read")

    monkeypatch.setattr("backend.pipeline.ingest_process.file_sha256", refuse)
    monkeypatch.setattr("backend.app.services.originals.LinkedFolder.local_path", refuse)
    monkeypatch.setattr("backend.pipeline.ingest_process.PILImage.open", refuse)
    jobs = len(forest.jobs())

    result = forest.scan()
    assert (result.new, result.changed, result.gone, result.job_id) == (0, 0, 0, None)
    assert len(forest.jobs()) == jobs


def test_a_no_change_rescan_of_a_large_folder_is_a_few_queries(linked, monkeypatch, tmp_db):
    """60k known files: the rows load in one query and nothing is done per file."""
    from backend.tests.conftest import QueryCounter

    count = 60_000
    keys = [f"Author/Pack {i // 50}/map {i}.png" for i in range(count)]
    with linked.api.SessionLocal() as db:
        source = LibrarySource(kind="folder", location=str(linked.root), state=SOURCE_ONLINE)
        db.add(source)
        db.flush()
        db.execute(
            insert(SourceFile),
            [
                {"source_id": source.id, "rel_key": k, "size": 1, "mtime_ns": 1, "state": "image"}
                for k in keys
            ],
        )
        db.commit()
    entries = [originals.LinkedEntry(k, 1, 1) for k in keys]
    monkeypatch.setattr(originals.LinkedFolder, "list", lambda self: iter(entries))

    engine, _ = tmp_db
    started = time.perf_counter()
    with QueryCounter(engine) as counter:
        result = linked.scan()
    elapsed = time.perf_counter() - started
    assert result.job_id is None and result.new == 0
    assert counter.count < 25, counter.statements
    assert elapsed < 10, elapsed


# Rescans: add, delete, move, edit


def test_added_files_join_their_pack(forest):
    write_tree(forest.root, {"Czepeku/Forest/Forest_Dusk.png": image_bytes(3)})
    result = forest.sync()
    assert result.new == 1
    images = forest.images()
    assert len(images) == 3
    assert len({image.group_id for image in images.values()}) == 1  # merged by (name, author)


def test_a_deleted_file_is_missing_until_it_is_back(forest):
    night = forest.root / "Czepeku/Forest/Forest_Night.png"
    mtime = night.stat().st_mtime_ns
    image = forest.images()["Czepeku/Forest/Forest_Night.png"]
    night.unlink()

    result = forest.sync()
    assert (result.gone, result.job_id) == (1, None)
    assert forest.image(image.id)["file_state"] == "missing"
    r = forest.client.get(f"/api/v1/images/{image.id}/file")
    assert r.status_code == 404
    assert forest.client.get(f"/api/v1/images/{image.id}/thumbnail").status_code == 200
    assert forest.status()["missing_count"] == 1

    night.write_bytes(FOREST["Czepeku/Forest/Forest_Night.png"])
    touch(night, mtime)
    result = forest.sync()
    assert result.back == 1
    assert forest.image(image.id)["file_state"] == "ok"
    assert forest.status()["missing_count"] == 0


def test_a_moved_file_keeps_its_image(forest):
    image = forest.images()["Czepeku/Forest/Forest_Day.png"]
    (forest.root / "Czepeku/Moved").mkdir()
    os.rename(forest.root / "Czepeku/Forest/Forest_Day.png", forest.root / "Czepeku/Moved/Day.png")

    result = forest.sync()
    assert (result.new, result.gone) == (1, 1)
    images = forest.images()
    assert len(images) == 2
    assert images["Czepeku/Moved/Day.png"].id == image.id  # repointed, metadata kept
    assert "Czepeku/Forest/Forest_Day.png" not in forest.rows()  # the old row is gone
    assert forest.image(image.id)["file_state"] == "ok"
    assert forest.client.get(f"/api/v1/images/{image.id}/file").status_code == 200


# Edited files: refresh (§4.5)

DAY = "Czepeku/Forest/Forest_Day.png"
NIGHT = "Czepeku/Forest/Forest_Night.png"


def thumbnail_files() -> set[str]:
    base = get_thumbnail_store().base_dir
    return {p.name for p in base.rglob("*") if p.is_file() and ".incoming" not in p.parts}


def thumbnails_of(image: Image) -> set[str]:
    """Every size of an image's thumbnail (they share a stem and extension)."""
    key = str(image.thumbnail_key)
    stem, ext = key.rsplit("_", 1)[0], key.rsplit(".", 1)[1]
    return {f"{stem}_{w}x{h}.{ext}" for w, h in settings.thumbnail_sizes}


def tag_values(api, image_id: int) -> set[str]:
    with api.SessionLocal() as db:
        return {t.value for t in db.query(Tag).filter(Tag.image_id == image_id)}


def embed_as(monkeypatch, value: float, before=None) -> list:
    """Embeddings of ``value``; ``before`` runs first, once (to act mid-refresh)."""
    calls: list = []

    def embed(paths, **kwargs):
        if before is not None and not calls:
            before()
        calls.append(paths)
        return [[value] * 8 for _ in paths]

    monkeypatch.setattr(
        "backend.pipeline.tasks.embedding_generation.batch_generate_clip_embeddings", embed
    )
    return calls


def test_an_edited_file_refreshes_its_image_in_place(forest, monkeypatch):
    old = forest.images()[DAY]
    r = forest.client.patch(
        f"/api/v1/images/{old.id}",
        json={
            "name": "Sunlit Glade",
            "gridded": True,
            "grid_width": 20,
            "grid_height": 15,
            "grid_type": "square",
        },
    )
    assert r.status_code == 200, r.text
    with forest.api.SessionLocal() as db:
        db.add(Tag(image_id=old.id, category="biome", value="glade", source="manual"))
        db.commit()
    tags = tag_values(forest.api, old.id)
    old_thumbnails = thumbnails_of(old)
    assert old_thumbnails <= thumbnail_files()
    jobs = len(forest.jobs())

    edited = image_bytes(9, size=(80, 60))
    (forest.root / DAY).write_bytes(edited)
    embed_as(monkeypatch, 0.9)
    result = forest.sync()
    assert (result.changed, result.refresh, result.new) == (1, 1, 1)
    assert len(forest.jobs()) == jobs + 1
    assert forest.api.detail(str(result.job_id))["counts"]["done"] == 1

    images = forest.images()
    assert len(images) == 2
    image = images[DAY]
    body = forest.image(image.id)
    # The same image, with everything the user gave it
    assert image.id == old.id
    assert (image.name, image.group_id, image.image_type) == (
        "Sunlit Glade",
        old.group_id,
        "battlemap",
    )
    assert (image.author, image.import_job_id) == (old.author, old.import_job_id)
    assert "glade" in tags and tag_values(forest.api, image.id) == tags
    assert (body["gridded"], body["grid_width"], body["grid_height"]) == (True, 20, 15)
    assert body["grid_source"] == "user"
    # and what comes from the file, from the edited one
    assert (image.width, image.height) == (80, 60)
    assert image.file_size == len(edited)
    assert image.content_hash == image.stored_hash == hashlib.sha256(edited).hexdigest()
    assert image.pixel_hash != old.pixel_hash and image.phash is not None
    assert image.thumbnail_key != old.thumbnail_key
    assert thumbnails_of(image) <= thumbnail_files()
    assert not old_thumbnails & thumbnail_files()  # the old thumbnails are gone
    vector = forest.api.vectors.get_embedding(image.id)
    assert vector is not None and vector[0] == pytest.approx(0.9)
    assert forest.client.get(f"/api/v1/images/{image.id}/file").content == edited
    assert body["file_state"] == "ok"

    row = forest.rows()[DAY]
    stat = (forest.root / DAY).stat()
    assert (row.state, row.image_id) == (FILE_IMAGE, image.id)
    assert (row.size, row.mtime_ns) == (stat.st_size, stat.st_mtime_ns)
    assert row.content_hash == image.content_hash
    assert forest.sync().job_id is None  # nothing more to do


def test_a_touched_file_is_not_read_again(forest, monkeypatch):
    day = forest.root / DAY
    old = forest.images()[DAY]
    touch(day, day.stat().st_mtime_ns + 5_000_000_000)

    def refuse(*args, **kwargs):
        raise AssertionError("the file was processed")

    # Hashed to tell, but never decoded, thumbnailed or embedded
    monkeypatch.setattr("backend.pipeline.ingest_process.plan_decode", refuse)
    monkeypatch.setattr("backend.pipeline.ingest_process._decode", refuse)
    monkeypatch.setattr(
        "backend.pipeline.tasks.embedding_generation.batch_generate_clip_embeddings", refuse
    )
    result = forest.sync()
    assert (result.changed, result.refresh) == (1, 1)
    assert forest.api.detail(str(result.job_id))["counts"]["done"] == 1
    image = forest.images()[DAY]
    assert (image.id, image.thumbnail_key, image.content_hash) == (
        old.id,
        old.thumbnail_key,
        old.content_hash,
    )
    assert forest.image(image.id)["file_state"] == "ok"
    assert forest.rows()[DAY].mtime_ns == day.stat().st_mtime_ns
    assert forest.sync().job_id is None


def test_a_failed_refresh_leaves_the_image_as_it_was(forest):
    old = forest.images()[DAY]
    good = image_bytes(9, size=(80, 60))
    (forest.root / DAY).write_bytes(good[: len(good) // 2])  # saved halfway

    result = forest.sync()
    assert result.refresh == 1
    assert forest.api.detail(str(result.job_id))["counts"]["failed"] == 1
    image = forest.images()[DAY]
    assert (image.id, image.thumbnail_key, image.content_hash, image.width) == (
        old.id,
        old.thumbnail_key,
        old.content_hash,
        old.width,
    )
    assert thumbnails_of(old) <= thumbnail_files()
    assert forest.image(image.id)["file_state"] == "ok"
    row = forest.rows()[DAY]
    assert (row.state, row.image_id) == (FILE_IMAGE, old.id)
    assert row.reason
    assert forest.sync().job_id is None  # the version that failed isn't read again

    (forest.root / DAY).write_bytes(good)  # saved in full
    assert forest.sync().refresh == 1
    image = forest.images()[DAY]
    assert (image.id, image.width) == (old.id, 80)
    assert forest.rows()[DAY].reason is None


def test_an_image_removed_during_its_refresh_is_skipped(forest, monkeypatch):
    old = forest.images()[DAY]
    night = forest.images()[NIGHT]
    (forest.root / DAY).write_bytes(image_bytes(9))
    job_id = forest.scan().job_id

    def remove():
        assert forest.client.delete(f"/api/v1/images/{old.id}").status_code == 200

    embed_as(monkeypatch, 0.5, before=remove)
    forest.api.worker.drain()
    detail = forest.api.detail(str(job_id))
    assert detail["counts"]["skipped"] == 1 and detail["status"] == "completed"
    with forest.api.SessionLocal() as db:
        item = db.query(ImportItem).filter(ImportItem.job_id == job_id).one()
        assert item.error_reason == REFRESH_GONE_REASON
    assert list(forest.images()) == [NIGHT]
    assert forest.rows()[DAY].state == FILE_REMOVED
    assert thumbnail_files() == thumbnails_of(night)  # nothing left of the refresh
    assert forest.sync().job_id is None  # and it stays removed


def test_a_touched_file_whose_image_was_removed_is_skipped(forest, monkeypatch):
    day = forest.root / DAY
    old = forest.images()[DAY]
    touch(day, day.stat().st_mtime_ns + 5_000_000_000)
    job_id = forest.scan().job_id
    real = q.record_refresh_unchanged

    def remove_first(unchanged):
        assert forest.client.delete(f"/api/v1/images/{old.id}").status_code == 200
        return real(unchanged)

    monkeypatch.setattr("backend.pipeline.ingest_process.record_refresh_unchanged", remove_first)
    forest.api.worker.drain()
    assert forest.api.detail(str(job_id))["counts"]["skipped"] == 1
    assert forest.rows()[DAY].state == FILE_REMOVED


def test_a_refresh_never_overwrites_a_user_edit_made_meanwhile(forest, monkeypatch):
    old = forest.images()[DAY]
    (forest.root / DAY).write_bytes(image_bytes(9, size=(80, 60)))
    forest.scan()

    def edit():
        r = forest.client.patch(
            f"/api/v1/images/{old.id}",
            json={"name": "Renamed", "gridded": True, "grid_width": 8, "grid_height": 6},
        )
        assert r.status_code == 200, r.text

    embed_as(monkeypatch, 0.5, before=edit)
    forest.api.worker.drain()
    body = forest.image(old.id)
    assert body["name"] == "Renamed"
    assert (body["grid_width"], body["grid_height"], body["grid_source"]) == (8, 6, "user")
    assert (body["width"], body["height"]) == (80, 60)  # refreshed all the same


def test_an_edited_file_with_another_maps_bytes_is_refreshed_in_place(forest):
    """The user's file is the truth: it stays its image's, even holding another's bytes."""
    images = forest.images()
    (forest.root / DAY).write_bytes(FOREST[NIGHT])

    result = forest.sync()
    assert result.refresh == 1
    assert forest.api.detail(str(result.job_id))["counts"]["done"] == 1
    after = forest.images()
    assert {k: v.id for k, v in after.items()} == {k: v.id for k, v in images.items()}
    assert after[DAY].content_hash == after[NIGHT].content_hash
    rows = forest.rows()
    assert rows[DAY].state == rows[NIGHT].state == FILE_IMAGE


def test_a_cancelled_refresh_is_offered_again(forest):
    old = forest.images()[DAY]
    (forest.root / DAY).write_bytes(image_bytes(9, size=(80, 60)))
    job_id = forest.scan().job_id
    assert forest.client.post(f"{BASE}/{job_id}/cancel").status_code == 200
    row = forest.rows()[DAY]
    assert (row.state, row.image_id) == (FILE_IMAGE, old.id)  # still the image's file
    assert forest.images()[DAY].width == old.width

    result = forest.sync()
    assert result.refresh == 1
    assert forest.images()[DAY].width == 80


def test_a_refresh_is_queued_once_while_it_waits(forest):
    (forest.root / DAY).write_bytes(image_bytes(9))
    first = forest.scan()
    (forest.root / DAY).write_bytes(image_bytes(10, size=(70, 50)))  # edited again, unread
    second = forest.scan()
    assert first.refresh == 1 and second.job_id is None
    forest.api.worker.drain()
    image = forest.images()[DAY]
    assert image.content_hash == hashlib.sha256(image_bytes(10, size=(70, 50))).hexdigest()
    assert forest.sync().job_id is None


def test_a_duplicate_takes_over_when_the_original_goes(linked):
    write_tree(linked.root, {"A/Map.png": image_bytes(5), "B/Map copy.png": image_bytes(5)})
    linked.sync()
    rows = linked.rows()
    assert {rows["A/Map.png"].state, rows["B/Map copy.png"].state} == {FILE_IMAGE, FILE_DUPLICATE}
    image_key = next(k for k, r in rows.items() if r.state == FILE_IMAGE)
    other_key = next(k for k, r in rows.items() if r.state == FILE_DUPLICATE)
    image = linked.images()[image_key]

    (linked.root / str(image_key)).unlink()
    result = linked.sync()
    assert result.moved == 1
    assert linked.images()[other_key].id == image.id
    assert linked.image(image.id)["file_state"] == "ok"


def test_the_source_tree_is_never_changed(linked):
    write_tree(linked.root, FOREST)
    linked.sync()
    write_tree(linked.root, {"Czepeku/Cave/Cave.png": image_bytes(4)})
    (linked.root / "Czepeku/Forest/Forest_Night.png").unlink()
    os.rename(linked.root / "Czepeku/Forest/Forest_Day.png", linked.root / "Czepeku/Day.png")
    before = tree_digest(linked.root)
    linked.sync()
    image = next(iter(linked.images().values()))
    linked.client.delete(f"/api/v1/images/{image.id}")
    linked.client.post(f"{LIBRARY}/linked/remove-missing")
    linked.client.delete(f"{LIBRARY}/linked")
    assert tree_digest(linked.root) == before


# Processing guards


def test_a_file_changed_while_read_is_read_again(linked, monkeypatch):
    path = linked.root / "A/Map.png"
    write_tree(linked.root, {"A/Map.png": image_bytes(6)})
    linked.scan()

    calls = []

    def embed_and_edit(paths, **kwargs):
        if not calls:  # the file changes while the first attempt is being read
            with open(path, "ab") as f:
                f.write(b"more")
        calls.append(paths)
        return [[0.1] * 8 for _ in paths]

    monkeypatch.setattr(
        "backend.pipeline.tasks.embedding_generation.batch_generate_clip_embeddings",
        embed_and_edit,
    )
    linked.api.worker.drain()
    assert len(calls) == 2
    images = linked.images()
    assert list(images) == ["A/Map.png"]
    row = linked.rows()["A/Map.png"]
    assert (row.size, row.mtime_ns) == (path.stat().st_size, path.stat().st_mtime_ns)
    assert linked.sync().job_id is None


def test_a_key_outside_the_folder_is_never_read(linked, tmp_path):
    secret = tmp_path / "secret.png"
    secret.write_bytes(image_bytes(7))
    with linked.api.SessionLocal() as db:
        source = LibrarySource(kind="folder", location=str(linked.root), state=SOURCE_ONLINE)
        db.add(source)
        db.flush()
        row = SourceFile(
            source_id=source.id, rel_key="../secret.png", size=1, mtime_ns=1, state=FILE_IMAGE
        )
        db.add(row)
        db.flush()
        image = Image(filename="secret.png", source_file_id=row.id)
        db.add(image)
        db.commit()
        image_id = image.id
    assert linked.client.get(f"/api/v1/images/{image_id}/file").status_code == 404


# Offline


def test_an_offline_folder_marks_nothing_missing(forest):
    image = next(iter(forest.images().values()))
    away = forest.root.with_name("Unplugged")
    os.rename(forest.root, away)

    result = forest.sync()
    assert result.state == "offline"
    assert all(row.missing_since is None for row in forest.rows().values())
    assert forest.status()["state"] == "offline"
    assert forest.image(image.id)["file_state"] == "offline"
    r = forest.client.get(f"/api/v1/images/{image.id}/file")
    assert r.status_code == 503 and r.json()["detail"] == "Maps isn't available"
    assert forest.client.get(f"/api/v1/images/{image.id}/thumbnail").status_code == 200

    os.rename(away, forest.root)
    result = forest.sync()
    assert result.state == "online" and result.job_id is None
    assert forest.image(image.id)["file_state"] == "ok"
    assert forest.status()["state"] == "online"


def test_a_scan_waits_while_its_folder_is_offline(linked):
    write_tree(linked.root, {"A/Map.png": image_bytes(8)})
    job_id = linked.scan().job_id
    away = linked.root.with_name("Unplugged")
    os.rename(linked.root, away)
    linked.api.worker.drain()
    summary = next(j for j in linked.client.get(BASE).json()["jobs"] if j["id"] == job_id)
    assert summary["counts"]["ready"] == 1
    assert summary["waiting_for"] == ["Maps"]  # named, never a path

    os.rename(away, linked.root)
    linked.api.worker.drain()
    assert linked.api.detail(job_id)["counts"]["done"] == 1


# Removing images (§4.6, §4.7)


def test_a_removed_image_stays_removed(forest):
    images = forest.images()
    day = images["Czepeku/Forest/Forest_Day.png"]
    thumbnails = get_thumbnail_store()
    assert thumbnails.exists(str(day.thumbnail_key))

    assert forest.client.delete(f"/api/v1/images/{day.id}").status_code == 200
    assert not thumbnails.exists(str(day.thumbnail_key))  # its thumbnails go
    assert (forest.root / "Czepeku/Forest/Forest_Day.png").exists()  # its file never does
    assert forest.rows()["Czepeku/Forest/Forest_Day.png"].state == FILE_REMOVED

    # Removed in the group editor too
    night = images["Czepeku/Forest/Forest_Night.png"]
    group = forest.client.get(f"/api/v1/groups/{night.group_id}").json()
    r = forest.client.put(
        f"/api/v1/groups/{night.group_id}",
        json={"base_name": group["base_name"], "images": [], "delete_image_ids": [night.id]},
    )
    assert r.status_code == 200, r.text
    assert not thumbnails.exists(str(night.thumbnail_key))
    assert forest.rows()["Czepeku/Forest/Forest_Night.png"].state == FILE_REMOVED

    assert forest.sync().job_id is None
    assert forest.images() == {}


def test_remove_missing_maps(forest):
    (forest.root / "Czepeku/Forest/Forest_Night.png").unlink()
    forest.sync()
    r = forest.client.post(f"{LIBRARY}/linked/remove-missing")
    assert r.status_code == 200 and r.json() == {"removed": 1}
    assert list(forest.images()) == ["Czepeku/Forest/Forest_Day.png"]
    assert forest.status()["missing_count"] == 0
    assert forest.rows()["Czepeku/Forest/Forest_Night.png"].state == FILE_REMOVED

    # Put back, it stays removed
    write_tree(forest.root, {"Czepeku/Forest/Forest_Night.png": image_bytes(2)})
    assert forest.sync().job_id is None
    assert len(forest.images()) == 1


def test_stop_using_the_folder(forest):
    before = tree_digest(forest.root)
    r = forest.client.delete(f"{LIBRARY}/linked")
    assert r.status_code == 200 and r.json() == {"removed": 2}
    with forest.api.SessionLocal() as db:
        assert db.query(Image).count() == 0
        assert db.query(SourceFile).count() == 0
    status = forest.status()
    assert status["state"] == "detached" and status["image_count"] == 0
    # Until the configuration drops the folder, it isn't scanned again
    assert forest.client.post(f"{LIBRARY}/scan", json={"reason": "manual"}).status_code == 409
    assert forest.scan().state == "detached"
    assert tree_digest(forest.root) == before


def test_stop_using_waits_for_a_scan_or_a_batch_in_progress(forest, monkeypatch):
    """Removing the folder's images under a running scan or commit would race them."""
    scanner = linked_scanner.get_linked_scanner()
    monkeypatch.setattr(scanner, "_running", True)
    assert forest.client.delete(f"{LIBRARY}/linked").status_code == 409
    monkeypatch.setattr(scanner, "_running", False)

    (forest.root / DAY).write_bytes(image_bytes(9))
    job_id = forest.scan().job_id
    with forest.api.SessionLocal() as db:  # its batch is being processed
        db.query(ImportItem).filter(ImportItem.job_id == job_id).update({"state": st.PROCESSING})
        db.commit()
    assert forest.client.delete(f"{LIBRARY}/linked").status_code == 409
    assert forest.jobs()[-1].status == st.JOB_CANCELLED  # the cancellation is kept
    assert len(forest.images()) == 2
    assert forest.status()["state"] == "online"


def test_undo_is_refused_for_a_linked_scan(forest):
    job_id = forest.jobs()[0].id
    r = forest.client.delete(f"{BASE}/{job_id}")
    assert r.status_code == 409
    assert len(forest.images()) == 2


def test_cancel_forgets_the_files_it_skipped(linked):
    write_tree(linked.root, {"A/One.png": image_bytes(1), "A/Two.png": image_bytes(2)})
    job_id = linked.scan().job_id
    r = linked.client.post(f"{BASE}/{job_id}/cancel")
    assert r.status_code == 200 and r.json()["affected"] == 2
    assert linked.rows() == {}
    with linked.api.SessionLocal() as db:
        assert db.query(ImportItem).filter(ImportItem.source_file_id.isnot(None)).count() == 0

    result = linked.sync()  # offered again
    assert result.new == 2
    assert len(linked.images()) == 2


def test_purge_never_touches_the_linked_folder(forest):
    before = tree_digest(forest.root)
    job_id = forest.client.delete("/api/v1/system/library").json()["job_id"]
    for _ in range(100):
        status = forest.client.get(f"/api/v1/jobs/{job_id}").json()["status"]
        if status in ("completed", "failed"):
            break
        time.sleep(0.05)
    assert status == "completed"
    with forest.api.SessionLocal() as db:
        assert db.query(Image).count() == 0
        assert db.query(SourceFile).count() == 0
        assert db.query(LibrarySource).count() == 0
    assert tree_digest(forest.root) == before
    # The folder is still linked: its next scan adds its maps again
    assert forest.sync().new == 2


# The scan endpoint and startup


def test_scan_endpoint(linked):
    write_tree(linked.root, {"A/Map.png": image_bytes(1)})
    scanner = linked_scanner.get_linked_scanner()
    r = linked.client.post(f"{LIBRARY}/scan", json={"reason": "manual"})
    assert r.status_code == 202 and r.json() == {"started": True}
    for _ in range(200):
        if not scanner.running:
            break
        time.sleep(0.02)
    assert len(linked.rows()) == 1

    # A focus scan within a minute of the last one is ignored; Check for changes isn't
    assert linked.client.post(f"{LIBRARY}/scan", json={"reason": "focus"}).json() == {
        "started": False
    }
    linked.api.set_app_setting("linked_rescan_minutes", 0)
    scanner._last_started = None
    assert linked.client.post(f"{LIBRARY}/scan", json={"reason": "focus"}).json() == {
        "started": False
    }
    assert linked.client.post(f"{LIBRARY}/scan", json={"reason": "bogus"}).status_code == 422


def test_scan_endpoint_without_a_linked_folder(test_client):
    r = test_client.post(f"{LIBRARY}/scan", json={"reason": "manual"})
    assert r.status_code == 409


def test_startup_reconciles_the_source(forest, monkeypatch, tmp_path):
    write_tree(forest.root, {"Czepeku/Cave/Cave.png": image_bytes(4)})
    job_id = forest.scan().job_id

    # The folder is configured somewhere else (a new drive letter): unfinished scans
    # wait on its new place
    moved = tmp_path / "Moved Maps"
    os.rename(forest.root, moved)
    monkeypatch.setattr(settings, "linked_library_dir", moved)
    with forest.api.SessionLocal() as db:
        reconcile_linked_source(db)
        source = db.query(LibrarySource).one()
        assert (source.location, source.state) == (str(moved), SOURCE_ONLINE)
        assert db.get(ImportJob, job_id).source_roots == f'["{moved}"]'  # pyright: ignore[reportOptionalMemberAccess]
    forest.api.worker.drain()
    assert forest.api.detail(job_id)["counts"]["done"] == 1

    # No folder configured: detached, and its images are offline
    write_tree(moved, {"Czepeku/Cave/Cave 2.png": image_bytes(5)})
    job_id = forest.scan().job_id
    monkeypatch.setattr(settings, "linked_library_dir", None)
    originals.forget_availability()
    with forest.api.SessionLocal() as db:
        reconcile_linked_source(db)
        assert db.query(LibrarySource).one().state == SOURCE_DETACHED
        assert db.get(ImportJob, job_id).status == st.JOB_CANCELLED  # pyright: ignore[reportOptionalMemberAccess]
    status = forest.status()
    assert status["state"] == "detached" and status["image_count"] == 3
    image = next(iter(forest.images().values()))
    assert forest.image(image.id)["file_state"] == "offline"

    # Configured but missing on disk: offline, not an error
    monkeypatch.setattr(settings, "linked_library_dir", tmp_path / "Unplugged")
    with forest.api.SessionLocal() as db:
        reconcile_linked_source(db)
        assert db.query(LibrarySource).one().state == SOURCE_OFFLINE


def test_pending_rows_without_an_item_are_queued_again(linked):
    """A pending file whose item was lost (or left out by a scan's limit) is offered again."""
    write_tree(linked.root, {"A/Map.png": image_bytes(1)})
    linked.scan()
    with linked.api.SessionLocal() as db:
        db.query(ImportItem).delete()
        db.commit()
    assert linked.rows()["A/Map.png"].state == FILE_PENDING
    result = linked.sync()
    assert result.new == 1
    assert list(linked.images()) == ["A/Map.png"]


def test_a_failed_file_is_retried_when_it_changes(linked):
    broken = linked.root / "A/Broken.png"
    write_tree(linked.root, {"A/Broken.png": b"not a png"})
    job_id = linked.sync().job_id
    row = linked.rows()["A/Broken.png"]
    assert (row.state, row.reason) == ("failed", "File content doesn't match its type")

    # Retry in the report reads it again (and it fails again)
    r = linked.client.post(f"{BASE}/{job_id}/retry")
    assert r.status_code == 200 and r.json()["affected"] == 1
    assert linked.rows()["A/Broken.png"].state == FILE_PENDING
    linked.api.worker.drain()
    assert linked.rows()["A/Broken.png"].state == "failed"
    assert linked.sync().job_id is None  # unchanged: not read again

    broken.write_bytes(image_bytes(3))  # fixed
    assert linked.sync().changed == 1
    assert list(linked.images()) == ["A/Broken.png"]


def test_an_oversized_file_fails_without_being_read(linked):
    linked.api.set_app_setting("max_import_file_size", 10)
    write_tree(linked.root, {"A/Big.png": image_bytes(1)})
    linked.sync()
    row = linked.rows()["A/Big.png"]
    assert (row.state, row.reason) == ("failed", q.OVERSIZED_REASON)
    assert linked.images() == {}


def test_files_over_a_scans_limit_are_added_by_the_next_scan(linked, monkeypatch):
    monkeypatch.setattr(settings, "max_local_import_items", 2)
    write_tree(linked.root, {f"A/Map {i}.png": image_bytes(i + 1) for i in range(3)})
    assert linked.sync().new == 2
    assert linked.sync().new == 1
    assert len(linked.images()) == 3
    assert linked.sync().job_id is None


def test_a_scan_interrupted_before_sealing_is_redone(linked, monkeypatch):
    write_tree(linked.root, {"A/Map.png": image_bytes(1)})

    def crash(job_id):
        raise RuntimeError("power cut")

    with monkeypatch.context() as patched:
        patched.setattr(linked_scan, "seal_scan", crash)
        assert linked_scanner.get_linked_scanner().scan() is None  # failed, logged
    assert [job.planned_at for job in linked.jobs()] == [None]

    result = linked.sync()
    assert result.new == 1
    jobs = linked.jobs()
    assert len(jobs) == 1 and jobs[0].planned_at is not None
    assert list(linked.images()) == ["A/Map.png"]
