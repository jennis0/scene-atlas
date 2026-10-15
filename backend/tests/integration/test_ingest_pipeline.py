"""Integration tests for the per-item ingest pipeline (ADR-018).

Real SQLite, real filesystem, real thumbnails, colours and hashes. Embeddings and
LanceDB are faked. The worker is driven synchronously with ``drain()``.

Covers design/ingest-redesign.md §11: happy path, group resolution, the three
dedup tiers, import-as-copy, file/transient/system errors, crash recovery,
cancel/pause/retry, round-robin scheduling, bytes lost, vector reconciliation
and commit-failure cleanup.
"""

from __future__ import annotations

import errno
import hashlib
import io
import sqlite3
import uuid
from datetime import timedelta
from pathlib import Path

import numpy as np
import pytest
from PIL import Image as PILImage
from sqlalchemy.exc import OperationalError

from backend.app.models import Image, ImageGroup, ImportGroup, ImportItem, ImportJob
from backend.app.services import ingest_state as st
from backend.app.services.image_store import ImageStore
from backend.pipeline import ingest_process, ingest_queue
from backend.pipeline.ingest_queue import (
    ManifestEntry,
    add_manifest_items,
    cancel_job,
    claim_next_batch,
    create_job,
    import_as_copy,
    mark_bytes_received,
    pause_job,
    plan_job,
    resume_job,
    retry_items,
    staged_path,
)
from backend.pipeline.ingest_worker import IngestWorker
from backend.pipeline.pipeline_config import PipelineConfig
from backend.pipeline.vector_reconcile import reconcile_vectors

EMBEDDING = [0.1] * 8


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class FakeVectors:
    """Minimal stand-in for LanceDBService."""

    def __init__(self):
        self.rows: dict[int, list[float]] = {}
        self.fail_writes = False

    def batch_add_embeddings(self, items):
        if self.fail_writes:
            return False
        for item in items:
            self.rows[item["image_id"]] = item["embedding"]
        return True

    def get_all_ids(self):
        return set(self.rows)

    def delete_embeddings(self, ids):
        for image_id in ids:
            self.rows.pop(image_id, None)
        return True


@pytest.fixture
def env(tmp_db, tmp_path, monkeypatch):
    engine, SessionLocal = tmp_db
    from backend.app import services

    monkeypatch.setattr("backend.app.config.settings.database_url", str(engine.url))
    monkeypatch.setattr("backend.app.config.settings.staging_dir", tmp_path / "staging")
    library = ImageStore(tmp_path / "library")
    thumbnails = ImageStore(tmp_path / "thumbnails")
    monkeypatch.setattr(services, "_image_store", library)
    monkeypatch.setattr(services, "_thumbnail_store", thumbnails)

    vectors = FakeVectors()
    monkeypatch.setattr(ingest_process, "get_lancedb_service", lambda: vectors)
    monkeypatch.setattr("backend.pipeline.vector_reconcile.get_lancedb_service", lambda: vectors)
    monkeypatch.setattr(
        "backend.pipeline.tasks.embedding_generation.batch_generate_clip_embeddings",
        lambda paths, **kw: [list(EMBEDDING) for _ in paths],
    )
    # Retries are immediately claimable unless a test says otherwise.
    monkeypatch.setattr(st, "retry_delay", lambda attempts: timedelta(0))

    class Env:
        pass

    e = Env()
    e.SessionLocal = SessionLocal
    e.library = library
    e.thumbnails = thumbnails
    e.vectors = vectors
    e.probe_reason = None
    e.config = PipelineConfig(enable_image_grid_detection=False, ingestion_batch_size=4)
    e.worker = IngestWorker(
        config_loader=lambda: e.config,
        probe=lambda: e.probe_reason,
        probe_interval=0.0,
    )
    return e


def image_bytes(seed: int = 0, fmt: str = "PNG", size=(64, 48), **save_kwargs) -> bytes:
    rng = np.random.default_rng(seed)
    pixels = rng.integers(0, 255, (size[1], size[0], 3), dtype=np.uint8)
    buf = io.BytesIO()
    PILImage.fromarray(pixels).save(buf, format=fmt, **save_kwargs)
    return buf.getvalue()


def make_job(env, files: dict[str, bytes | None], *, upload=True) -> str:
    """Create, manifest, plan and (optionally) upload a job. None = manifest only."""
    with env.SessionLocal() as db:
        job = create_job(db, label="test")
        items = add_manifest_items(
            db,
            job,
            [ManifestEntry(path, size=len(data) if data else None) for path, data in files.items()],
        )
        plan_job(db, job.id)
        if upload:
            for item in items:
                data = files[item.relative_path]
                if data is not None and item.state == st.AWAITING_BYTES:
                    stage_bytes(db, item, data)
        db.commit()
        return job.id


def stage_bytes(db, item: ImportItem, data: bytes) -> None:
    key = f"{uuid.uuid4().hex}{Path(item.relative_path).suffix.lower()}"
    path = staged_path(item.job_id, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    mark_bytes_received(db, item, staging_key=key, source_hash=hashlib.sha256(data).hexdigest())


def items_by_path(env, job_id) -> dict[str, ImportItem]:
    with env.SessionLocal() as db:
        rows = db.query(ImportItem).filter(ImportItem.job_id == job_id).all()
        for row in rows:
            db.expunge(row)
        return {row.relative_path: row for row in rows}


def job_status(env, job_id) -> str:
    with env.SessionLocal() as db:
        return db.get(ImportJob, job_id).status


def store_files(store: ImageStore) -> list[Path]:
    return [p for p in store.base_dir.rglob("*") if p.is_file()]


# ---------------------------------------------------------------------------
# Happy path and groups
# ---------------------------------------------------------------------------


def test_happy_path_imports_everything(env):
    job_id = make_job(
        env,
        {
            "Czepeku/Island Fort/IslandFort_Night.png": image_bytes(1),
            "Czepeku/Island Fort/IslandFort_Day.png": image_bytes(2),
            "Czepeku/Swamp Hut/SwampHut.jpg": image_bytes(3, fmt="JPEG"),
        },
    )
    assert env.worker.drain() >= 1

    items = items_by_path(env, job_id)
    assert {i.state for i in items.values()} == {st.DONE}
    assert job_status(env, job_id) == st.JOB_COMPLETED

    with env.SessionLocal() as db:
        images = db.query(Image).all()
        assert len(images) == 3
        groups = {g.base_name for g in db.query(ImageGroup).all()}
        assert groups == {"Island Fort", "Swamp Hut"}
        for image in images:
            assert image.author == "Czepeku"
            assert image.import_job_id == job_id
            assert image.content_hash and image.pixel_hash and image.phash is not None
            assert image.stored_hash == image.content_hash
            assert env.library.get_path(image.storage_key).exists()
            assert env.thumbnails.get_path(image.thumbnail_key).exists()
            assert image.colors  # real colour extraction ran
        night = next(i for i in images if "Night" in i.filename)
        assert ("lighting", "night") in {(t.category, t.value) for t in night.tags}

    # Every image indexed; staged bytes and temp files cleaned up.
    assert len(env.vectors.rows) == 3
    assert not any(p.is_file() for p in (env.library.base_dir / ".incoming").rglob("*"))
    assert not any(p.is_file() for p in staged_path(job_id, "x").parent.glob("*"))


def test_three_thumbnail_sizes_written(env):
    job_id = make_job(env, {"A/Map/Map.png": image_bytes(1, size=(1200, 900))})
    env.worker.drain()
    with env.SessionLocal() as db:
        image = db.query(Image).one()
        stem = Path(image.thumbnail_key).name.split("_")[0]
    names = sorted(p.name for p in store_files(env.thumbnails))
    assert names == sorted(f"{stem}_{w}x{w}.jpg" for w in (150, 400, 800))
    with PILImage.open(env.thumbnails.get_path(f"{stem}_800x800.jpg")) as large:
        assert large.size == (800, 600)
    assert job_status(env, job_id) == st.JOB_COMPLETED


def test_group_merges_into_existing_gallery_group(env):
    with env.SessionLocal() as db:
        existing = ImageGroup(base_name="Island Fort", author="Czepeku")
        db.add(existing)
        db.commit()
        existing_id = existing.id

    job_id = make_job(env, {"Czepeku/Island Fort/IslandFort_Rain.png": image_bytes(4)})
    with env.SessionLocal() as db:
        group = db.query(ImportGroup).filter(ImportGroup.job_id == job_id).one()
        assert group.merged_into_existing is True
        assert group.image_group_id == existing_id

    env.worker.drain()
    with env.SessionLocal() as db:
        assert db.query(Image).one().group_id == existing_id
        assert db.query(ImageGroup).count() == 1


def test_manifest_validation_fails_unsupported_and_oversized(env):
    with env.SessionLocal() as db:
        job = create_job(db)
        items = add_manifest_items(
            db,
            job,
            [
                ManifestEntry("Notes/readme.txt", size=10),
                ManifestEntry("Big/Map/huge.png", size=10_000),
                ManifestEntry("Ok/Map/ok.png", size=10),
            ],
            max_file_size=1_000,
        )
        db.commit()
        reasons = {i.relative_path: (i.state, i.error_reason) for i in items}
    assert reasons["Notes/readme.txt"] == (st.FAILED, "Unsupported file type")
    assert reasons["Big/Map/huge.png"] == (st.FAILED, "File is larger than the import size limit")
    assert reasons["Ok/Map/ok.png"] == (st.AWAITING_BYTES, None)


def test_manifest_cannot_change_after_seal(env):
    with env.SessionLocal() as db:
        job = create_job(db)
        add_manifest_items(db, job, [ManifestEntry("A/B/c.png")])
        plan_job(db, job.id)
        with pytest.raises(ingest_queue.ManifestSealedError):
            add_manifest_items(db, job, [ManifestEntry("A/B/d.png")])


def test_unplanned_items_are_not_claimed(env):
    with env.SessionLocal() as db:
        job = create_job(db)
        (item,) = add_manifest_items(db, job, [ManifestEntry("A/B/c.png")])
        stage_bytes(db, item, image_bytes(1))
        db.commit()
    assert env.worker.drain() == 0


# ---------------------------------------------------------------------------
# Duplicates
# ---------------------------------------------------------------------------


def test_byte_duplicate_of_library_image_is_skipped(env):
    data = image_bytes(5)
    first = make_job(env, {"A/Map/one.png": data})
    env.worker.drain()
    second = make_job(env, {"B/Other/copy.png": data})
    env.worker.drain()

    item = items_by_path(env, second)["B/Other/copy.png"]
    assert item.state == st.DUPLICATE
    assert item.duplicate_tier == "bytes"
    with env.SessionLocal() as db:
        original = db.query(Image).filter(Image.import_job_id == first).one()
        assert item.duplicate_of_image_id == original.id
        assert db.query(Image).count() == 1
    # Staged bytes kept so "Import as new copy" works without re-upload.
    assert staged_path(second, item.staging_key).exists()
    assert job_status(env, second) == st.JOB_COMPLETED


def test_pixel_duplicate_across_formats_is_skipped(env):
    pixels = PILImage.open(io.BytesIO(image_bytes(6)))
    webp = io.BytesIO()
    pixels.save(webp, format="WEBP", lossless=True)
    make_job(env, {"A/Map/one.png": image_bytes(6)})
    env.worker.drain()
    second = make_job(env, {"A/Map/one.webp": webp.getvalue()})
    env.worker.drain()
    item = items_by_path(env, second)["A/Map/one.webp"]
    assert (item.state, item.duplicate_tier) == (st.DUPLICATE, "pixels")


def test_duplicate_within_one_batch(env):
    data = image_bytes(7)
    job_id = make_job(env, {"A/Map/a.png": data, "A/Map/b.png": data})
    env.worker.drain()
    states = sorted(i.state for i in items_by_path(env, job_id).values())
    assert states == [st.DONE, st.DUPLICATE]


def test_all_duplicates_job_completes(env):
    """Regression (F2): a re-import where every file is already present must finish."""
    files = {"A/Map/a.png": image_bytes(8), "A/Map/b.png": image_bytes(9)}
    make_job(env, files)
    env.worker.drain()
    again = make_job(env, files)
    env.worker.drain()
    assert {i.state for i in items_by_path(env, again).values()} == {st.DUPLICATE}
    assert job_status(env, again) == st.JOB_COMPLETED


def test_import_as_copy_creates_independent_image(env):
    data = image_bytes(10)
    make_job(env, {"A/Map/one.png": data})
    env.worker.drain()
    second = make_job(env, {"B/Other/copy.png": data})
    env.worker.drain()

    with env.SessionLocal() as db:
        assert import_as_copy(db, second) == 1
        db.commit()
    assert job_status(env, second) == st.JOB_ACTIVE
    env.worker.drain()

    item = items_by_path(env, second)["B/Other/copy.png"]
    assert item.state == st.DONE
    with env.SessionLocal() as db:
        images = db.query(Image).order_by(Image.id).all()
        assert len(images) == 2
        original, copy = images
        assert copy.id == item.image_id
        assert copy.storage_key != original.storage_key
        assert copy.thumbnail_key != original.thumbnail_key
        assert copy.group_id != original.group_id
    assert len(env.vectors.rows) == 2
    assert job_status(env, second) == st.JOB_COMPLETED


def test_import_as_copy_without_bytes_waits_for_upload(env):
    data = image_bytes(11)
    make_job(env, {"A/Map/one.png": data})
    env.worker.drain()
    second = make_job(env, {"B/Other/copy.png": data})
    env.worker.drain()
    item = items_by_path(env, second)["B/Other/copy.png"]
    staged_path(second, item.staging_key).unlink()

    with env.SessionLocal() as db:
        import_as_copy(db, second)
        db.commit()
    item = items_by_path(env, second)["B/Other/copy.png"]
    assert (item.state, item.staging_key, item.allow_duplicate) == (
        st.AWAITING_BYTES,
        None,
        True,
    )


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


def test_corrupt_file_fails_alone(env):
    job_id = make_job(env, {"A/Map/good.png": image_bytes(12), "A/Map/bad.png": b"not an image"})
    env.worker.drain()
    items = items_by_path(env, job_id)
    assert items["A/Map/good.png"].state == st.DONE
    bad = items["A/Map/bad.png"]
    assert (bad.state, bad.error_kind) == (st.FAILED, "file")
    assert bad.error_reason == "Image is corrupt or not a supported format"
    assert job_status(env, job_id) == st.JOB_COMPLETED
    # Failed items keep their staged bytes for retry.
    assert staged_path(job_id, bad.staging_key).exists()


def _locked() -> OperationalError:
    return OperationalError("INSERT", {}, sqlite3.OperationalError("database is locked"))


def test_transient_commit_error_is_retried(env, monkeypatch):
    calls = {"n": 0}
    real_commit = ingest_process.commit_batch

    def flaky(prepared):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _locked()
        return real_commit(prepared)

    monkeypatch.setattr(ingest_process, "commit_batch", flaky)
    job_id = make_job(env, {"A/Map/a.png": image_bytes(13)})
    env.worker.drain()
    item = items_by_path(env, job_id)["A/Map/a.png"]
    assert (item.state, item.attempts) == (st.DONE, 2)
    assert job_status(env, job_id) == st.JOB_COMPLETED


def test_transient_error_waits_for_backoff(env, monkeypatch):
    def always_locked(prepared):
        raise _locked()

    monkeypatch.setattr(st, "retry_delay", lambda attempts: timedelta(hours=1))
    monkeypatch.setattr(ingest_process, "commit_batch", always_locked)
    job_id = make_job(env, {"A/Map/a.png": image_bytes(14)})
    assert env.worker.drain() == 1
    item = items_by_path(env, job_id)["A/Map/a.png"]
    assert item.state == st.READY and item.retry_after is not None
    assert job_status(env, job_id) == st.JOB_ACTIVE


def test_transient_error_gives_up_after_max_attempts(env, monkeypatch):
    def always_locked(prepared):
        raise _locked()

    monkeypatch.setattr(ingest_process, "commit_batch", always_locked)
    job_id = make_job(env, {"A/Map/a.png": image_bytes(15)})
    env.worker.drain()
    item = items_by_path(env, job_id)["A/Map/a.png"]
    assert (item.state, item.attempts, item.error_kind) == (st.FAILED, st.MAX_ATTEMPTS, "transient")
    assert job_status(env, job_id) == st.JOB_COMPLETED


def test_commit_failure_removes_placed_files(env, monkeypatch):
    def explode(**kwargs):
        raise _locked()

    monkeypatch.setattr(ingest_process, "build_search_text", explode)
    monkeypatch.setattr(st, "retry_delay", lambda attempts: timedelta(hours=1))
    make_job(env, {"A/Map/a.png": image_bytes(16)})
    env.worker.drain()
    assert store_files(env.library) == []
    assert store_files(env.thumbnails) == []
    with env.SessionLocal() as db:
        assert db.query(Image).count() == 0


def test_system_probe_pauses_queue(env):
    job_id = make_job(env, {"A/Map/a.png": image_bytes(17)})
    env.probe_reason = "No AI model is available"
    assert env.worker.drain() == 0
    status = env.worker.status()
    assert status.system_paused and status.system_reason == "No AI model is available"
    assert items_by_path(env, job_id)["A/Map/a.png"].state == st.READY

    env.probe_reason = None
    assert env.worker.probe_now() is None
    assert env.worker.drain() == 1
    assert job_status(env, job_id) == st.JOB_COMPLETED
    assert not env.worker.status().system_paused


def test_disk_full_pauses_instead_of_failing(env, monkeypatch):
    def no_space(src, dst):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(ingest_process.shutil, "copyfile", no_space)
    job_id = make_job(env, {"A/Map/a.png": image_bytes(18), "A/Map/b.png": image_bytes(19)})
    assert env.worker.run_once()
    items = items_by_path(env, job_id).values()
    assert {(i.state, i.attempts) for i in items} == {(st.READY, 0)}
    assert env.worker.status().system_reason == "Not enough disk space to process image"
    assert store_files(env.thumbnails) == []  # temp thumbnails cleaned up


def test_missing_staged_bytes_asks_for_reupload(env):
    job_id = make_job(env, {"A/Map/a.png": image_bytes(20)})
    item = items_by_path(env, job_id)["A/Map/a.png"]
    staged_path(job_id, item.staging_key).unlink()
    env.worker.drain()
    item = items_by_path(env, job_id)["A/Map/a.png"]
    assert (item.state, item.staging_key) == (st.AWAITING_BYTES, None)
    assert item.error_reason == "The uploaded file is missing; upload it again"
    assert job_status(env, job_id) == st.JOB_ACTIVE


# ---------------------------------------------------------------------------
# Recovery
# ---------------------------------------------------------------------------


def test_recovery_requeues_interrupted_items(env):
    job_id = make_job(env, {"A/Map/a.png": image_bytes(21)})
    _, claimed = claim_next_batch(None, 10)  # simulate a crash mid-batch
    assert len(claimed) == 1
    (env.library.base_dir / ".incoming").mkdir(parents=True, exist_ok=True)
    (env.library.base_dir / ".incoming" / "leftover.png").write_bytes(b"x")

    assert env.worker.recover() == {"recovered": 1, "crashed": 0}
    assert not (env.library.base_dir / ".incoming").exists()
    env.worker.drain()
    assert items_by_path(env, job_id)["A/Map/a.png"].state == st.DONE


def test_item_that_keeps_crashing_is_failed(env):
    job_id = make_job(env, {"A/Map/a.png": image_bytes(22)})
    for _ in range(st.MAX_ATTEMPTS - 1):
        claim_next_batch(None, 10)  # process dies mid-batch...
        assert env.worker.recover() == {"recovered": 1, "crashed": 0}
    claim_next_batch(None, 10)  # ...for the third time
    assert env.worker.recover() == {"recovered": 0, "crashed": 1}
    item = items_by_path(env, job_id)["A/Map/a.png"]
    assert (item.state, item.error_reason) == (st.FAILED, "Repeatedly crashed during processing")
    assert job_status(env, job_id) == st.JOB_COMPLETED


# ---------------------------------------------------------------------------
# User actions and scheduling
# ---------------------------------------------------------------------------


def test_cancel_keeps_finished_work(env):
    env.config = PipelineConfig(enable_image_grid_detection=False, ingestion_batch_size=2)
    job_id = make_job(env, {f"A/Map/{n}.png": image_bytes(30 + n) for n in range(4)})
    assert env.worker.run_once()
    with env.SessionLocal() as db:
        assert cancel_job(db, job_id) == 2
        db.commit()
    assert env.worker.drain() == 0
    states = sorted(i.state for i in items_by_path(env, job_id).values())
    assert states == [st.DONE, st.DONE, st.SKIPPED, st.SKIPPED]
    assert job_status(env, job_id) == st.JOB_CANCELLED
    with env.SessionLocal() as db:
        assert db.query(Image).count() == 2


def test_pause_and_resume(env):
    job_id = make_job(env, {"A/Map/a.png": image_bytes(40)})
    with env.SessionLocal() as db:
        pause_job(db, job_id)
        db.commit()
    assert env.worker.drain() == 0
    assert job_status(env, job_id) == st.JOB_PAUSED
    with env.SessionLocal() as db:
        resume_job(db, job_id)
        db.commit()
    env.worker.drain()
    assert job_status(env, job_id) == st.JOB_COMPLETED


def test_retry_failed_reopens_completed_job(env):
    job_id = make_job(env, {"A/Map/bad.png": b"garbage"})
    env.worker.drain()
    assert job_status(env, job_id) == st.JOB_COMPLETED
    with env.SessionLocal() as db:
        assert retry_items(db, job_id) == 1
        item = db.query(ImportItem).filter(ImportItem.job_id == job_id).one()
        assert (item.state, item.attempts, item.error_reason) == (st.READY, 0, None)
        stage_bytes_path = staged_path(job_id, item.staging_key)
        stage_bytes_path.write_bytes(image_bytes(41))  # e.g. user fixed the file
        item.source_hash = None
        db.commit()
    assert job_status(env, job_id) == st.JOB_ACTIVE
    env.worker.drain()
    assert items_by_path(env, job_id)["A/Map/bad.png"].state == st.DONE


def test_retry_without_staged_bytes_waits_for_upload(env):
    job_id = make_job(env, {"A/Map/bad.png": b"garbage"})
    env.worker.drain()
    item = items_by_path(env, job_id)["A/Map/bad.png"]
    staged_path(job_id, item.staging_key).unlink()
    with env.SessionLocal() as db:
        retry_items(db, job_id)
        db.commit()
    assert items_by_path(env, job_id)["A/Map/bad.png"].state == st.AWAITING_BYTES


def test_round_robin_between_jobs(env):
    a = make_job(env, {f"A/Map/{n}.png": image_bytes(50 + n) for n in range(4)})
    b = make_job(env, {f"B/Map/{n}.png": image_bytes(60 + n) for n in range(4)})
    order = []
    cursor = None
    for _ in range(4):
        cursor, claimed = claim_next_batch(cursor, 1)
        order.append(cursor)
    assert order == [a, b, a, b]


def test_items_claimed_in_group_order(env):
    job_id = make_job(
        env,
        {
            "Author/Zeta/z1.png": image_bytes(70),
            "Author/Alpha/a1.png": image_bytes(71),
            "Author/Zeta/z2.png": image_bytes(72),
        },
    )
    _, claimed = claim_next_batch(None, 10)
    groups = [c.import_group_id for c in claimed]
    # Each group's items are contiguous.
    assert groups == sorted(groups, key=groups.index)
    assert len(set(groups)) == 2
    assert job_id


# ---------------------------------------------------------------------------
# Vectors
# ---------------------------------------------------------------------------


def test_vector_write_failure_is_repaired_by_reconciliation(env):
    env.vectors.fail_writes = True
    job_id = make_job(env, {"A/Map/a.png": image_bytes(80), "A/Map/b.png": image_bytes(81)})
    env.worker.drain()
    assert job_status(env, job_id) == st.JOB_COMPLETED
    assert env.vectors.rows == {}

    env.vectors.fail_writes = False
    env.vectors.rows[999_999] = list(EMBEDDING)  # orphaned vector
    result = reconcile_vectors()
    assert result == {"missing": 2, "repaired": 2, "unrepairable": 0, "orphaned": 1}
    with env.SessionLocal() as db:
        assert env.vectors.get_all_ids() == {i for (i,) in db.query(Image.id).all()}


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------


def test_write_session_holds_the_write_lock(env, tmp_db):
    engine, _ = tmp_db
    db_path = engine.url.database
    with ingest_queue.write_session():
        other = sqlite3.connect(db_path, timeout=0, isolation_level=None)
        try:
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                other.execute("BEGIN IMMEDIATE")
        finally:
            other.close()
