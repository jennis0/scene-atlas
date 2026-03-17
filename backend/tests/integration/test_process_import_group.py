"""Integration tests: process_import_group and process_import_job flows.

Tests the batch pipeline end-to-end with real SQLite, real filesystem, and
mocked heavy services (CLIP, LanceDB, thumbnails, color extraction).

Covers:
- Happy path: all files processed, DB records created
- Progress tracking: ImportGroupJob status and counters updated
- Missing file handling: partial/total staging absence
- Reuse path: duplicate detection skips copy + CLIP
- Multi-group coordinator: process_import_job sequences groups, cleans staging
- Error recovery: DB failure marks group failed without crashing the job
"""

import uuid

import pytest

from backend.app.models.database import Image, ImageGroup, ImportGroupJob, ImportJob

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def _patch_db_for_flows(monkeypatch, tmp_db):
    """Point settings.database_url at the test DB so flows use it."""
    engine, SessionLocal = tmp_db
    monkeypatch.setattr("backend.app.config.settings.database_url", str(engine.url))
    return engine, SessionLocal


@pytest.fixture
def _patch_image_store(monkeypatch, tmp_path):
    """Redirect ImageStore writes to a temp directory."""
    from backend.app.services.image_store import ImageStore

    store = ImageStore(tmp_path / "store")
    monkeypatch.setattr("backend.pipeline.ingestion.get_image_store", lambda: store)
    monkeypatch.setattr("backend.pipeline.prepare.get_image_store", lambda: store)
    return store


@pytest.fixture
def seeded_import_job(_patch_db_for_flows):
    """Seed an ImportJob + one ImportGroupJob in the test DB."""
    engine, SessionLocal = _patch_db_for_flows
    job_id = f"job-{uuid.uuid4().hex[:8]}"
    group_job_id = f"grp-{uuid.uuid4().hex[:8]}"

    db = SessionLocal()
    try:
        db.add(ImportJob(id=job_id, status="active", total_files=2))
        db.flush()
        db.add(
            ImportGroupJob(
                id=group_job_id,
                job_id=job_id,
                group_name="Test Map",
                author="TestAuthor",
                total_files=2,
                status="running",
            )
        )
        db.commit()
    finally:
        db.close()

    return engine, SessionLocal, job_id, group_job_id


# ---------------------------------------------------------------------------
# Helper: minimal file-info dict for _run_group / process_import_group
# ---------------------------------------------------------------------------


def _file_dict(relative_path: str, name: str = "Test Map", **overrides) -> dict:
    """Build a minimal file metadata dict as produced by analyse_upload."""
    base = {
        "relative_path": relative_path,
        "name": name,
        "tags": [],
        "gridded": None,
        "grid_width": None,
        "grid_height": None,
        "subgroup": None,
        "image_type": "battlemap",
        "content_hash": None,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# TestProcessImportGroupBasic
# ---------------------------------------------------------------------------


class TestProcessImportGroupBasic:
    """Happy-path tests for process_import_group."""

    def test_happy_path_returns_correct_counts(
        self,
        tmp_staging,
        mock_heavy_services,
        seeded_import_job,
        _patch_image_store,
    ):
        """Two staged files → processed=2, failed=0 in return value."""
        from backend.pipeline.ingestion import process_import_group

        engine, SessionLocal, job_id, group_job_id = seeded_import_job

        files = [
            _file_dict("TestAuthor/TestMap/TestMap_Night_Grid.jpg", name="Test Map Night"),
            _file_dict("TestAuthor/TestMap/TestMap_Summer.jpg", name="Test Map Summer"),
        ]

        result = process_import_group(
            job_id=job_id,
            group_job_id=group_job_id,
            staging_dir=str(tmp_staging),
            author="TestAuthor",
            group_name="Test Map",
            files=files,
        )

        assert result["processed"] == 2
        assert result["failed"] == 0
        assert result["total"] == 2

    def test_images_saved_to_db(
        self,
        tmp_staging,
        mock_heavy_services,
        seeded_import_job,
        _patch_image_store,
    ):
        """Image records appear in the DB with the correct author."""
        from backend.pipeline.ingestion import process_import_group

        engine, SessionLocal, job_id, group_job_id = seeded_import_job

        files = [
            _file_dict("TestAuthor/TestMap/TestMap_Night_Grid.jpg"),
            _file_dict("TestAuthor/TestMap/TestMap_Summer.jpg"),
        ]

        process_import_group(
            job_id=job_id,
            group_job_id=group_job_id,
            staging_dir=str(tmp_staging),
            author="TestAuthor",
            group_name="Test Map",
            files=files,
        )

        db = SessionLocal()
        try:
            images = db.query(Image).filter(Image.author == "TestAuthor").all()
            assert len(images) == 2
        finally:
            db.close()

    def test_images_placed_in_group(
        self,
        tmp_staging,
        mock_heavy_services,
        seeded_import_job,
        _patch_image_store,
    ):
        """Images are linked to an ImageGroup with the correct base_name."""
        from backend.pipeline.ingestion import process_import_group

        engine, SessionLocal, job_id, group_job_id = seeded_import_job

        files = [
            _file_dict("TestAuthor/TestMap/TestMap_Night_Grid.jpg"),
        ]

        process_import_group(
            job_id=job_id,
            group_job_id=group_job_id,
            staging_dir=str(tmp_staging),
            author="TestAuthor",
            group_name="Test Map",
            files=files,
        )

        db = SessionLocal()
        try:
            group = db.query(ImageGroup).filter(ImageGroup.base_name == "Test Map").first()
            assert group is not None
            assert group.author == "TestAuthor"
            assert len(group.images) == 1
        finally:
            db.close()

    def test_file_copied_to_image_store(
        self,
        tmp_staging,
        mock_heavy_services,
        seeded_import_job,
        _patch_image_store,
    ):
        """Each processed image is copied into the image store."""
        from backend.pipeline.ingestion import process_import_group

        engine, SessionLocal, job_id, group_job_id = seeded_import_job
        store = _patch_image_store

        files = [_file_dict("TestAuthor/TestMap/TestMap_Summer.jpg")]

        process_import_group(
            job_id=job_id,
            group_job_id=group_job_id,
            staging_dir=str(tmp_staging),
            author="TestAuthor",
            group_name="Test Map",
            files=files,
        )

        db = SessionLocal()
        try:
            image = db.query(Image).filter(Image.author == "TestAuthor").first()
            assert image is not None
            assert store.exists(image.storage_key)
        finally:
            db.close()


# ---------------------------------------------------------------------------
# TestProcessImportGroupProgress
# ---------------------------------------------------------------------------


class TestProcessImportGroupProgress:
    """ImportGroupJob and ImportJob status/counter updates."""

    def test_group_job_marked_completed(
        self,
        tmp_staging,
        mock_heavy_services,
        seeded_import_job,
        _patch_image_store,
    ):
        """ImportGroupJob.status transitions to 'completed' after the flow."""
        from backend.pipeline.ingestion import process_import_group

        engine, SessionLocal, job_id, group_job_id = seeded_import_job

        files = [
            _file_dict("TestAuthor/TestMap/TestMap_Night_Grid.jpg"),
            _file_dict("TestAuthor/TestMap/TestMap_Summer.jpg"),
        ]

        process_import_group(
            job_id=job_id,
            group_job_id=group_job_id,
            staging_dir=str(tmp_staging),
            author="TestAuthor",
            group_name="Test Map",
            files=files,
        )

        db = SessionLocal()
        try:
            group_job = db.query(ImportGroupJob).filter(ImportGroupJob.id == group_job_id).first()
            assert group_job.status == "completed"
            assert group_job.processed_files == 2
            assert group_job.failed_files == 0
        finally:
            db.close()

    def test_import_job_completes_after_all_groups_done(
        self,
        tmp_staging,
        mock_heavy_services,
        seeded_import_job,
        _patch_image_store,
    ):
        """ImportJob.status transitions to 'completed' when all groups finish."""
        from backend.pipeline.ingestion import process_import_group

        engine, SessionLocal, job_id, group_job_id = seeded_import_job

        files = [_file_dict("TestAuthor/TestMap/TestMap_Summer.jpg")]

        process_import_group(
            job_id=job_id,
            group_job_id=group_job_id,
            staging_dir=str(tmp_staging),
            author="TestAuthor",
            group_name="Test Map",
            files=files,
        )

        db = SessionLocal()
        try:
            job = db.query(ImportJob).filter(ImportJob.id == job_id).first()
            # All groups terminal → job auto-completes
            assert job.status == "completed"
            assert job.completed_at is not None
        finally:
            db.close()


# ---------------------------------------------------------------------------
# TestProcessImportGroupMissingFiles
# ---------------------------------------------------------------------------


class TestProcessImportGroupMissingFiles:
    """Partial and total staging-file absence."""

    def test_one_file_missing_counts_as_failed(
        self,
        tmp_staging,
        mock_heavy_services,
        seeded_import_job,
        _patch_image_store,
    ):
        """File absent from staging → counted as failed, does not crash."""
        from backend.pipeline.ingestion import process_import_group

        engine, SessionLocal, job_id, group_job_id = seeded_import_job

        files = [
            _file_dict("TestAuthor/TestMap/TestMap_Summer.jpg"),
            _file_dict("TestAuthor/TestMap/DoesNotExist.jpg"),  # not in staging
        ]

        result = process_import_group(
            job_id=job_id,
            group_job_id=group_job_id,
            staging_dir=str(tmp_staging),
            author="TestAuthor",
            group_name="Test Map",
            files=files,
        )

        assert result["processed"] == 1
        assert result["failed"] == 1

    def test_all_files_missing_group_completes_cleanly(
        self,
        tmp_staging,
        mock_heavy_services,
        seeded_import_job,
        _patch_image_store,
    ):
        """All files absent → processed=0, group still marked completed."""
        from backend.pipeline.ingestion import process_import_group

        engine, SessionLocal, job_id, group_job_id = seeded_import_job

        files = [
            _file_dict("Missing1.jpg"),
            _file_dict("Missing2.jpg"),
        ]

        result = process_import_group(
            job_id=job_id,
            group_job_id=group_job_id,
            staging_dir=str(tmp_staging),
            author="TestAuthor",
            group_name="Test Map",
            files=files,
        )

        assert result["processed"] == 0
        assert result["failed"] == 2

        # Group job should still be marked completed (not stuck in 'running')
        db = SessionLocal()
        try:
            group_job = db.query(ImportGroupJob).filter(ImportGroupJob.id == group_job_id).first()
            assert group_job.status == "completed"
        finally:
            db.close()


# ---------------------------------------------------------------------------
# TestProcessImportGroupReuseKey
# ---------------------------------------------------------------------------


class TestProcessImportGroupReuseKey:
    """Duplicate detection: reuse_storage_key skips copy + CLIP."""

    def test_reuse_storage_key_creates_db_record_with_same_key(
        self,
        tmp_staging,
        mock_heavy_services,
        seeded_import_job,
        _patch_image_store,
        make_test_image,
        tmp_path,
    ):
        """When reuse_storage_key is set, the new Image row uses that same key."""
        from backend.app.models.database import Color
        from backend.pipeline.ingestion import process_import_group

        engine, SessionLocal, job_id, group_job_id = seeded_import_job
        store = _patch_image_store

        # --- Create a source image: store file + DB record ---
        src_key = "aabbccdd1234.jpg"
        src_bytes = make_test_image(tmp_path / "source.jpg").read_bytes()
        store.put_bytes(src_key, src_bytes)

        db = SessionLocal()
        try:
            src_img = Image(
                filename="source.jpg",
                storage_key=src_key,
                name="Source Map",
                author="TestAuthor",
                width=20,
                height=20,
                file_size=len(src_bytes),
            )
            db.add(src_img)
            db.flush()
            db.add(Color(image_id=src_img.id, color_hex="#aabbcc", percentage=100.0, color_order=1))
            db.commit()
        finally:
            db.close()

        # --- A file_info that declares it is a duplicate of src_key ---
        # (relative_path does not need to exist in staging for the reuse path)
        files = [
            _file_dict(
                "TestAuthor/TestMap/TestMap_Summer.jpg",
                name="Test Map Summer",
                reuse_storage_key=src_key,
                reuse_thumbnail_key=None,
                content_hash="abc123",
            ),
        ]

        result = process_import_group(
            job_id=job_id,
            group_job_id=group_job_id,
            staging_dir=str(tmp_staging),
            author="TestAuthor",
            group_name="Test Map",
            files=files,
        )

        assert result["processed"] == 1
        assert result["failed"] == 0

        # The new Image row must share the same storage_key (no copy made)
        db = SessionLocal()
        try:
            images = db.query(Image).filter(Image.storage_key == src_key).all()
            # Both the source record and the new duplicate record
            assert len(images) == 2
        finally:
            db.close()


# ---------------------------------------------------------------------------
# TestProcessImportJob
# ---------------------------------------------------------------------------


class TestProcessImportJob:
    """Multi-group coordinator: process_import_job."""

    @pytest.fixture
    def two_group_job(self, _patch_db_for_flows):
        """Seed an ImportJob with two ImportGroupJob rows."""
        engine, SessionLocal = _patch_db_for_flows
        job_id = f"job-{uuid.uuid4().hex[:8]}"
        grp_a_id = f"grp-{uuid.uuid4().hex[:8]}"
        grp_b_id = f"grp-{uuid.uuid4().hex[:8]}"

        db = SessionLocal()
        try:
            db.add(ImportJob(id=job_id, status="active", total_files=3))
            db.flush()
            db.add(
                ImportGroupJob(
                    id=grp_a_id,
                    job_id=job_id,
                    group_name="Map A",
                    author="AuthorA",
                    total_files=2,
                    status="running",
                )
            )
            db.add(
                ImportGroupJob(
                    id=grp_b_id,
                    job_id=job_id,
                    group_name="Map B",
                    author="AuthorB",
                    total_files=1,
                    status="running",
                )
            )
            db.commit()
        finally:
            db.close()

        return engine, SessionLocal, job_id, grp_a_id, grp_b_id

    def test_two_groups_both_complete(
        self,
        tmp_staging,
        mock_heavy_services,
        two_group_job,
        _patch_image_store,
    ):
        """Both groups are processed; both ImportGroupJob rows end as 'completed'."""
        from backend.pipeline.ingestion import process_import_job

        engine, SessionLocal, job_id, grp_a_id, grp_b_id = two_group_job

        groups = [
            {
                "group_job_id": grp_a_id,
                "author": "AuthorA",
                "group_name": "Map A",
                "files": [
                    _file_dict("TestAuthor/TestMap/TestMap_Night_Grid.jpg", name="Map A Night"),
                    _file_dict("TestAuthor/TestMap/TestMap_Summer.jpg", name="Map A Summer"),
                ],
            },
            {
                "group_job_id": grp_b_id,
                "author": "AuthorB",
                "group_name": "Map B",
                "files": [
                    _file_dict("FlatFile.jpg", name="Map B"),
                ],
            },
        ]

        result = process_import_job(
            job_id=job_id,
            staging_dir=str(tmp_staging),
            groups=groups,
        )

        assert result["processed"] == 3
        assert result["failed"] == 0
        assert result["total_groups"] == 2

        db = SessionLocal()
        try:
            for grp_id in (grp_a_id, grp_b_id):
                grp = db.query(ImportGroupJob).filter(ImportGroupJob.id == grp_id).first()
                assert grp.status == "completed"
        finally:
            db.close()

    def test_staging_dir_preserved_after_job(
        self,
        tmp_staging,
        mock_heavy_services,
        two_group_job,
        _patch_image_store,
    ):
        """Staging directory is preserved after process_import_job (cleaned by cancel or expire_stale_jobs)."""
        from backend.pipeline.ingestion import process_import_job

        engine, SessionLocal, job_id, grp_a_id, grp_b_id = two_group_job

        groups = [
            {
                "group_job_id": grp_a_id,
                "author": "AuthorA",
                "group_name": "Map A",
                "files": [_file_dict("FlatFile.jpg")],
            },
            {
                "group_job_id": grp_b_id,
                "author": "AuthorB",
                "group_name": "Map B",
                "files": [_file_dict("TestAuthor/TestMap/TestMap_Summer.jpg")],
            },
        ]

        assert tmp_staging.exists()

        process_import_job(
            job_id=job_id,
            staging_dir=str(tmp_staging),
            groups=groups,
        )

        # Staging is NOT cleaned by process_import_job — it's handled by
        # /finalize, /cancel, or expire_stale_jobs
        assert tmp_staging.exists()

    def test_import_job_completed_after_all_groups_finish(
        self,
        tmp_staging,
        mock_heavy_services,
        two_group_job,
        _patch_image_store,
    ):
        """ImportJob.status becomes 'completed' when all groups finish."""
        from backend.pipeline.ingestion import process_import_job

        engine, SessionLocal, job_id, grp_a_id, grp_b_id = two_group_job

        groups = [
            {
                "group_job_id": grp_a_id,
                "author": "AuthorA",
                "group_name": "Map A",
                "files": [_file_dict("TestAuthor/TestMap/TestMap_Summer.jpg")],
            },
            {
                "group_job_id": grp_b_id,
                "author": "AuthorB",
                "group_name": "Map B",
                "files": [_file_dict("FlatFile.jpg")],
            },
        ]

        process_import_job(
            job_id=job_id,
            staging_dir=str(tmp_staging),
            groups=groups,
        )

        db = SessionLocal()
        try:
            job = db.query(ImportJob).filter(ImportJob.id == job_id).first()
            assert job.status == "completed"
        finally:
            db.close()


# ---------------------------------------------------------------------------
# TestProcessImportJobErrorHandling
# ---------------------------------------------------------------------------


class TestProcessImportJobErrorHandling:
    """Per-group exception isolation: one group failing does not abort the job."""

    @pytest.fixture
    def two_group_job(self, _patch_db_for_flows):
        engine, SessionLocal = _patch_db_for_flows
        job_id = f"job-{uuid.uuid4().hex[:8]}"
        grp_a_id = f"grp-{uuid.uuid4().hex[:8]}"
        grp_b_id = f"grp-{uuid.uuid4().hex[:8]}"

        db = SessionLocal()
        try:
            db.add(ImportJob(id=job_id, status="active", total_files=2))
            db.flush()
            db.add(
                ImportGroupJob(
                    id=grp_a_id,
                    job_id=job_id,
                    group_name="Map A",
                    author="AuthorA",
                    total_files=1,
                    status="running",
                )
            )
            db.add(
                ImportGroupJob(
                    id=grp_b_id,
                    job_id=job_id,
                    group_name="Map B",
                    author="AuthorB",
                    total_files=1,
                    status="running",
                )
            )
            db.commit()
        finally:
            db.close()

        return engine, SessionLocal, job_id, grp_a_id, grp_b_id

    def test_batch_db_failure_second_group_still_runs(
        self,
        tmp_staging,
        mock_heavy_services,
        two_group_job,
        _patch_image_store,
        monkeypatch,
    ):
        """If batch_save_to_database raises for group A, group B is still processed.

        _process_batch now catches DB save failures internally and marks the
        images as individually failed rather than letting the exception propagate
        to _run_group.  This means group A's _run_group completes normally
        (status="completed") but with 0 processed and 1 failed.  Group B is
        unaffected and completes with 1 processed.
        """
        from backend.pipeline.ingestion import process_import_job

        engine, SessionLocal, job_id, grp_a_id, grp_b_id = two_group_job

        from backend.pipeline.ingestion import batch_save_to_database as _original_fn

        call_count = {"n": 0}

        def _fail_first_then_succeed(image_data_list):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("Simulated DB failure for group A")
            return _original_fn(image_data_list)

        monkeypatch.setattr(
            "backend.pipeline.ingestion.batch_save_to_database",
            _fail_first_then_succeed,
        )

        groups = [
            {
                "group_job_id": grp_a_id,
                "author": "AuthorA",
                "group_name": "Map A",
                "files": [_file_dict("TestAuthor/TestMap/TestMap_Summer.jpg")],
            },
            {
                "group_job_id": grp_b_id,
                "author": "AuthorB",
                "group_name": "Map B",
                "files": [_file_dict("FlatFile.jpg")],
            },
        ]

        process_import_job(
            job_id=job_id,
            staging_dir=str(tmp_staging),
            groups=groups,
        )

        # Group A: DB save was caught inside _process_batch, so _run_group
        # completed normally — status is "completed" but with 0 processed and
        # 1 failed file (the batch-level failure is reflected in failed_files).
        db = SessionLocal()
        try:
            grp_a = db.query(ImportGroupJob).filter(ImportGroupJob.id == grp_a_id).first()
            assert grp_a.status == "completed"
            assert grp_a.processed_files == 0
            assert grp_a.failed_files == 1

            # Group B (second) should have processed its file successfully
            grp_b = db.query(ImportGroupJob).filter(ImportGroupJob.id == grp_b_id).first()
            assert grp_b.status == "completed"
            assert grp_b.processed_files == 1
        finally:
            db.close()


# ---------------------------------------------------------------------------
# TestProcessImportGroupTimestamps
# ---------------------------------------------------------------------------


class TestProcessImportGroupTimestamps:
    """Timestamp fields are populated correctly after the flow completes."""

    def test_completed_at_is_set_on_group_job(
        self,
        tmp_staging,
        mock_heavy_services,
        seeded_import_job,
        _patch_image_store,
    ):
        """ImportGroupJob.completed_at is populated (not None) after the flow."""
        from backend.pipeline.ingestion import process_import_group

        engine, SessionLocal, job_id, group_job_id = seeded_import_job

        files = [_file_dict("TestAuthor/TestMap/TestMap_Summer.jpg")]

        process_import_group(
            job_id=job_id,
            group_job_id=group_job_id,
            staging_dir=str(tmp_staging),
            author="TestAuthor",
            group_name="Test Map",
            files=files,
        )

        db = SessionLocal()
        try:
            group_job = db.query(ImportGroupJob).filter(ImportGroupJob.id == group_job_id).first()
            assert group_job.completed_at is not None
        finally:
            db.close()

    def test_completed_at_set_on_job_completion(
        self,
        tmp_staging,
        mock_heavy_services,
        seeded_import_job,
        _patch_image_store,
    ):
        """ImportJob.completed_at is set when all groups finish and job auto-completes."""
        from backend.pipeline.ingestion import process_import_group

        engine, SessionLocal, job_id, group_job_id = seeded_import_job

        files = [_file_dict("TestAuthor/TestMap/TestMap_Summer.jpg")]

        process_import_group(
            job_id=job_id,
            group_job_id=group_job_id,
            staging_dir=str(tmp_staging),
            author="TestAuthor",
            group_name="Test Map",
            files=files,
        )

        db = SessionLocal()
        try:
            job = db.query(ImportJob).filter(ImportJob.id == job_id).first()
            # All groups done → job auto-completes, completed_at is set
            assert job.status == "completed"
            assert job.completed_at is not None
        finally:
            db.close()


# ---------------------------------------------------------------------------
# TestStagingPreservation
# ---------------------------------------------------------------------------


class TestStagingPreservation:
    """Verify staging is NOT cleaned by process_import_group."""

    def test_staging_dir_preserved_after_single_group(
        self,
        tmp_staging,
        mock_heavy_services,
        seeded_import_job,
        _patch_image_store,
    ):
        """Staging directory survives process_import_group for future group submissions."""
        from backend.pipeline.ingestion import process_import_group

        engine, SessionLocal, job_id, group_job_id = seeded_import_job

        files = [_file_dict("TestAuthor/TestMap/TestMap_Summer.jpg")]

        assert tmp_staging.exists()

        process_import_group(
            job_id=job_id,
            group_job_id=group_job_id,
            staging_dir=str(tmp_staging),
            author="TestAuthor",
            group_name="Test Map",
            files=files,
        )

        # Staging must still exist — other groups may need it
        assert tmp_staging.exists()
        # Files inside staging should still be present
        assert any(tmp_staging.rglob("*.jpg"))
