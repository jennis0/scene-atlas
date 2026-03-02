"""Integration tests for import status, active imports, cleanup, and cancel endpoints.

These tests cover the pure-DB endpoints that don't require background processing:
  GET  /{job_id}/status
  GET  /active
  DELETE /cleanup
  POST /{job_id}/cancel
  POST /{job_id}/groups/{group_id}/cancel
  POST /check-hashes
"""

from datetime import UTC, datetime, timedelta

import pytest

from backend.app.models.database import Image, ImageGroup, ImportGroupJob, ImportJob

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_job(db, job_id: str, status: str = "staging", total_files: int = 2) -> ImportJob:
    job = ImportJob(id=job_id, status=status, total_files=total_files, source_label="TestImport")
    db.add(job)
    db.flush()
    return job


def _make_group_job(
    db,
    job_id: str,
    group_job_id: str,
    group_name: str = "TestGroup",
    status: str = "running",
    processed: int = 0,
    failed: int = 0,
    total: int = 2,
    completed_at: datetime | None = None,
) -> ImportGroupJob:
    gj = ImportGroupJob(
        id=group_job_id,
        job_id=job_id,
        group_name=group_name,
        author="TestAuthor",
        total_files=total,
        processed_files=processed,
        failed_files=failed,
        status=status,
        completed_at=completed_at,
    )
    db.add(gj)
    db.flush()
    return gj


@pytest.fixture
def seeded_job(test_client, tmp_db):
    """One ImportJob in 'staging' state, no group jobs."""
    _, SessionLocal = tmp_db
    db = SessionLocal()
    _make_job(db, "job001staging", status="staging")
    db.commit()
    db.close()
    yield test_client, "job001staging"


@pytest.fixture
def seeded_running_job(test_client, tmp_db):
    """One ImportJob in 'active' state + one running ImportGroupJob."""
    _, SessionLocal = tmp_db
    db = SessionLocal()
    _make_job(db, "jobrunninga", status="active", total_files=3)
    _make_group_job(db, "jobrunninga", "grp001", status="running", processed=1, total=3)
    db.commit()
    db.close()
    yield test_client, "jobrunninga", "grp001"


@pytest.fixture
def seeded_completed_job(test_client, tmp_db):
    """One ImportJob + one completed ImportGroupJob (completed very recently)."""
    _, SessionLocal = tmp_db
    db = SessionLocal()
    now = datetime.now(UTC).replace(tzinfo=None)
    job = _make_job(db, "jobdonebb", status="completed", total_files=2)
    job.completed_at = now
    _make_group_job(
        db,
        "jobdonebb",
        "grp002",
        status="completed",
        processed=2,
        total=2,
        completed_at=now,
    )
    db.commit()
    db.close()
    yield test_client, "jobdonebb"


# ---------------------------------------------------------------------------
# POST /api/v1/imports/check-hashes
# ---------------------------------------------------------------------------


class TestCheckHashes:
    def test_empty_request_returns_empty(self, test_client):
        resp = test_client.post("/api/v1/imports/check-hashes", json={"files": []})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_checked"] == 0
        assert data["duplicates_found"] == 0
        assert data["results"] == []

    def test_no_duplicates(self, test_client):
        resp = test_client.post(
            "/api/v1/imports/check-hashes",
            json={
                "files": [{"relative_path": "a.jpg", "filename": "a.jpg", "content_hash": "a" * 64}]
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_checked"] == 1
        assert data["duplicates_found"] == 0
        assert data["results"][0]["duplicate_of"] is None

    def test_detects_existing_image_as_duplicate(self, test_client, tmp_db):
        _, SessionLocal = tmp_db
        db = SessionLocal()
        group = ImageGroup(base_name="ExistingMap", author="Author")
        db.add(group)
        db.flush()
        img = Image(
            name="ExistingMap",
            filename="existing.jpg",
            author="Author",
            storage_key="existing_key.jpg",
            content_hash="c" * 64,
            group_id=group.id,
            media_type="image",
        )
        db.add(img)
        db.commit()
        db.close()

        resp = test_client.post(
            "/api/v1/imports/check-hashes",
            json={
                "files": [
                    {"relative_path": "new.jpg", "filename": "new.jpg", "content_hash": "c" * 64}
                ]
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["duplicates_found"] == 1
        dup = data["results"][0]["duplicate_of"]
        assert dup is not None
        assert dup["name"] == "ExistingMap"

    def test_mixed_results(self, test_client, tmp_db):
        """One duplicate and one new hash in the same batch."""
        _, SessionLocal = tmp_db
        db = SessionLocal()
        group = ImageGroup(base_name="SomeMap", author="Author")
        db.add(group)
        db.flush()
        db.add(
            Image(
                name="SomeMap",
                filename="s.jpg",
                author="Author",
                storage_key="some_key.jpg",
                content_hash="d" * 64,
                group_id=group.id,
                media_type="image",
            )
        )
        db.commit()
        db.close()

        resp = test_client.post(
            "/api/v1/imports/check-hashes",
            json={
                "files": [
                    {"relative_path": "dup.jpg", "filename": "dup.jpg", "content_hash": "d" * 64},
                    {"relative_path": "new.jpg", "filename": "new.jpg", "content_hash": "e" * 64},
                ]
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_checked"] == 2
        assert data["duplicates_found"] == 1


# ---------------------------------------------------------------------------
# GET /api/v1/imports/{job_id}/status
# ---------------------------------------------------------------------------


class TestImportStatus:
    def test_status_404_for_unknown_job(self, test_client):
        resp = test_client.get("/api/v1/imports/doesnotexist/status")
        assert resp.status_code == 404

    def test_staging_job_no_groups(self, seeded_job):
        client, job_id = seeded_job
        resp = client.get(f"/api/v1/imports/{job_id}/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["job_id"] == job_id
        assert data["status"] == "staging"
        assert data["groups"] == []

    def test_active_job_with_running_group(self, seeded_running_job):
        client, job_id, grp_id = seeded_running_job
        resp = client.get(f"/api/v1/imports/{job_id}/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "active"
        assert len(data["groups"]) == 1
        assert data["groups"][0]["status"] == "running"
        assert data["groups"][0]["processed_files"] == 1

    def test_all_groups_terminal_shows_completed(self, seeded_completed_job):
        client, job_id = seeded_completed_job
        resp = client.get(f"/api/v1/imports/{job_id}/status")
        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"

    def test_mixed_terminal_status_with_all_confirmed(self, test_client, tmp_db):
        """When all_confirmed=True and all groups terminal, job status is failed (has failures)."""
        _, SessionLocal = tmp_db
        db = SessionLocal()
        # Status is authoritative — set it to what transition_job_status would compute
        job = _make_job(db, "jobmixedcc", status="failed", total_files=4)
        job.all_confirmed = True
        _make_group_job(db, "jobmixedcc", "grp_ok", status="completed", processed=2, total=2)
        _make_group_job(
            db, "jobmixedcc", "grp_fail", group_name="FailGroup", status="failed", total=2
        )
        db.commit()
        db.close()

        resp = test_client.get("/api/v1/imports/jobmixedcc/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "failed"
        statuses = {g["group_name"]: g["status"] for g in data["groups"]}
        assert statuses["FailGroup"] == "failed"

    def test_awaiting_input_with_pending_groups(self, test_client, tmp_db):
        """When all submitted groups terminal but pending_groups > 0, status is awaiting_input."""
        _, SessionLocal = tmp_db
        db = SessionLocal()
        job = _make_job(db, "jobmixeddd", status="awaiting_input", total_files=4)
        job.all_confirmed = False
        job.pending_groups = 1  # One group still unconfirmed
        _make_group_job(db, "jobmixeddd", "grp_ok2", status="completed", processed=2, total=2)
        _make_group_job(
            db, "jobmixeddd", "grp_fail2", group_name="FailGroup", status="failed", total=2
        )
        db.commit()
        db.close()

        resp = test_client.get("/api/v1/imports/jobmixeddd/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "awaiting_input"
        assert data["detected_group_count"] == 3  # pending_groups + submitted
        assert data["pending_group_count"] == 1


# ---------------------------------------------------------------------------
# GET /api/v1/imports/active
# ---------------------------------------------------------------------------


class TestActiveImports:
    def test_staging_job_is_active(self, seeded_job):
        client, job_id = seeded_job
        resp = client.get("/api/v1/imports/active")
        assert resp.status_code == 200
        job_ids = [j["job_id"] for j in resp.json()["jobs"]]
        assert job_id in job_ids

    def test_running_job_is_active(self, seeded_running_job):
        client, job_id, _ = seeded_running_job
        resp = client.get("/api/v1/imports/active")
        assert resp.status_code == 200
        job_ids = [j["job_id"] for j in resp.json()["jobs"]]
        assert job_id in job_ids

    def test_recently_completed_job_is_active(self, seeded_completed_job):
        client, job_id = seeded_completed_job
        resp = client.get("/api/v1/imports/active")
        assert resp.status_code == 200
        job_ids = [j["job_id"] for j in resp.json()["jobs"]]
        assert job_id in job_ids

    def test_old_completed_job_excluded(self, test_client, tmp_db):
        """A job completed >1h ago should not appear in active imports."""
        _, SessionLocal = tmp_db
        db = SessionLocal()
        _make_job(db, "jobolddd", status="completed", total_files=1)
        old_time = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=2)
        _make_group_job(
            db,
            "jobolddd",
            "grp_old",
            status="completed",
            processed=1,
            total=1,
            completed_at=old_time,
        )
        db.commit()
        db.close()

        resp = test_client.get("/api/v1/imports/active")
        assert resp.status_code == 200
        job_ids = [j["job_id"] for j in resp.json()["jobs"]]
        assert "jobolddd" not in job_ids

    def test_response_includes_group_counts(self, seeded_running_job):
        client, job_id, _ = seeded_running_job
        resp = client.get("/api/v1/imports/active")
        jobs = {j["job_id"]: j for j in resp.json()["jobs"]}
        j = jobs[job_id]
        assert j["total_groups"] == 1
        assert j["running_groups"] == 1


# ---------------------------------------------------------------------------
# DELETE /api/v1/imports/cleanup
# ---------------------------------------------------------------------------


class TestCleanupImports:
    def test_cleanup_spares_staging_job(self, seeded_job):
        """Staging jobs represent active user sessions — cleanup must NOT delete them."""
        client, job_id = seeded_job
        resp = client.delete("/api/v1/imports/cleanup")
        assert resp.status_code == 200
        # Staging job should still exist
        status_resp = client.get(f"/api/v1/imports/{job_id}/status")
        assert status_resp.status_code == 200

    def test_cleanup_removes_completed_job(self, seeded_completed_job):
        client, job_id = seeded_completed_job
        resp = client.delete("/api/v1/imports/cleanup")
        assert resp.status_code == 200
        assert resp.json()["deleted"] >= 1

    def test_cleanup_spares_running_job(self, seeded_running_job):
        client, job_id, _ = seeded_running_job
        resp = client.delete("/api/v1/imports/cleanup")
        assert resp.status_code == 200
        # Running job must NOT be deleted
        status_resp = client.get(f"/api/v1/imports/{job_id}/status")
        assert status_resp.status_code == 200

    def test_cleanup_on_empty_db_returns_zero(self, test_client):
        resp = test_client.delete("/api/v1/imports/cleanup")
        assert resp.status_code == 200
        assert resp.json()["deleted"] == 0


# ---------------------------------------------------------------------------
# POST /api/v1/imports/{job_id}/cancel
# ---------------------------------------------------------------------------


class TestCancelImport:
    def test_cancel_staging_job(self, seeded_job, tmp_path):
        client, job_id = seeded_job
        # Create a fake staging dir so shutil.rmtree is exercised
        staging = tmp_path / job_id
        staging.mkdir(parents=True)

        resp = client.post(f"/api/v1/imports/{job_id}/cancel")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "cancelled"

    def test_cancel_404_for_missing_job(self, test_client):
        resp = test_client.post("/api/v1/imports/doesnotexist/cancel")
        assert resp.status_code == 404

    def test_cancel_with_running_groups_skips_staging_cleanup(self, seeded_running_job):
        client, job_id, _ = seeded_running_job
        resp = client.post(f"/api/v1/imports/{job_id}/cancel")
        assert resp.status_code == 200
        # staging_cleaned should be False because there's a running group
        assert resp.json()["staging_cleaned"] is False

    def test_cancel_all_terminal_groups_uses_transition(self, test_client, tmp_db):
        """Cancel with all-terminal groups delegates to transition_job_status.

        With one completed and one failed group, the result is 'failed' (not
        'completed') because the transition function correctly detects failures.
        """
        _, SessionLocal = tmp_db
        db = SessionLocal()
        _make_job(db, "jobtermeee", status="active", total_files=2)
        _make_group_job(db, "jobtermeee", "grp_t1", status="completed", total=1)
        _make_group_job(db, "jobtermeee", "grp_t2", group_name="Grp2", status="failed", total=1)
        db.commit()
        db.close()

        resp = test_client.post("/api/v1/imports/jobtermeee/cancel")
        assert resp.status_code == 200
        assert resp.json()["status"] == "failed"


# ---------------------------------------------------------------------------
# POST /api/v1/imports/{job_id}/groups/{group_id}/cancel
# ---------------------------------------------------------------------------


class TestCancelImportGroup:
    def test_cancel_running_group(self, seeded_running_job):
        client, job_id, grp_id = seeded_running_job
        resp = client.post(f"/api/v1/imports/{job_id}/groups/{grp_id}/cancel")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "cancelled"
        assert data["group_id"] == grp_id

    def test_cancel_group_404_for_missing(self, seeded_running_job):
        client, job_id, _ = seeded_running_job
        resp = client.post(f"/api/v1/imports/{job_id}/groups/zzznobody/cancel")
        assert resp.status_code == 404

    def test_cancel_already_completed_group_returns_400(self, seeded_completed_job, tmp_db):
        client, job_id = seeded_completed_job
        # Get the group_job_id from the DB
        _, SessionLocal = tmp_db
        db = SessionLocal()
        gj = db.query(ImportGroupJob).filter(ImportGroupJob.job_id == job_id).first()
        grp_id = gj.id
        db.close()

        resp = client.post(f"/api/v1/imports/{job_id}/groups/{grp_id}/cancel")
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# POST /api/v1/imports/{job_id}/finalize
# ---------------------------------------------------------------------------


class TestFinalizeImport:
    def test_finalize_staging_job(self, seeded_job):
        """Finalizing a staging job (no groups) completes it."""
        client, job_id = seeded_job
        resp = client.post(f"/api/v1/imports/{job_id}/finalize")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert data["already_terminal"] is False

    def test_finalize_active_job_with_completed_groups(self, test_client, tmp_db):
        """Finalize an active job whose groups are all done → completed + staging cleaned."""
        from backend.app.config import settings

        _, SessionLocal = tmp_db
        db = SessionLocal()
        _make_job(db, "jobfinact", status="active", total_files=2)
        _make_group_job(db, "jobfinact", "grp_fin1", status="completed", processed=2, total=2)
        db.commit()
        db.close()

        # Create fake staging dir
        staging_dir = settings.staging_dir / "jobfinact"
        staging_dir.mkdir(parents=True, exist_ok=True)
        (staging_dir / "dummy.txt").write_text("test")

        resp = test_client.post("/api/v1/imports/jobfinact/finalize")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert data["staging_cleaned"] is True
        assert not staging_dir.exists()

    def test_finalize_active_job_with_failures(self, test_client, tmp_db):
        """Finalize with one failed group → status becomes 'failed'."""
        _, SessionLocal = tmp_db
        db = SessionLocal()
        _make_job(db, "jobfinfail", status="active", total_files=3)
        _make_group_job(db, "jobfinfail", "grp_finok", status="completed", processed=2, total=2)
        _make_group_job(
            db, "jobfinfail", "grp_finfail", group_name="FailGrp", status="failed", total=1
        )
        db.commit()
        db.close()

        resp = test_client.post("/api/v1/imports/jobfinfail/finalize")
        assert resp.status_code == 200
        assert resp.json()["status"] == "failed"

    def test_finalize_rejects_running_groups(self, seeded_running_job):
        """Cannot finalize while groups are still running → 409."""
        client, job_id, _ = seeded_running_job
        resp = client.post(f"/api/v1/imports/{job_id}/finalize")
        assert resp.status_code == 409

    def test_finalize_idempotent_for_terminal(self, seeded_completed_job):
        """Finalizing an already-completed job returns OK with already_terminal=True."""
        client, job_id = seeded_completed_job
        resp = client.post(f"/api/v1/imports/{job_id}/finalize")
        assert resp.status_code == 200
        data = resp.json()
        assert data["already_terminal"] is True
        assert data["status"] == "completed"

    def test_finalize_404_for_missing_job(self, test_client):
        resp = test_client.post("/api/v1/imports/doesnotexist/finalize")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Active imports: pending_groups count
# ---------------------------------------------------------------------------


class TestActiveImportsPendingGroups:
    def test_active_job_shows_pending_groups(self, test_client, tmp_db):
        """An active job with pending_groups reports the count correctly."""
        _, SessionLocal = tmp_db
        db = SessionLocal()
        job = _make_job(db, "jobpending", status="awaiting_input", total_files=6)
        job.pending_groups = 2
        # One group submitted and completed
        _make_group_job(db, "jobpending", "grp_pa", status="completed", processed=2, total=2)
        db.commit()
        db.close()

        resp = test_client.get("/api/v1/imports/active")
        assert resp.status_code == 200
        jobs = {j["job_id"]: j for j in resp.json()["jobs"]}
        j = jobs["jobpending"]
        assert j["pending_groups"] == 2

    def test_status_endpoint_shows_pending_counts(self, test_client, tmp_db):
        """Status endpoint includes detected_group_count and pending_group_count."""
        _, SessionLocal = tmp_db
        db = SessionLocal()
        job = _make_job(db, "jobpendstat", status="staging", total_files=2)
        job.pending_groups = 2
        db.commit()
        db.close()

        resp = test_client.get("/api/v1/imports/jobpendstat/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["detected_group_count"] == 2  # pending_groups + 0 submitted
        assert data["pending_group_count"] == 2


# ---------------------------------------------------------------------------
# Init endpoint tests
# ---------------------------------------------------------------------------


class TestInitImport:
    def test_init_creates_uploading_job(self, test_client, tmp_db):
        """POST /init creates a job with status 'uploading'."""
        resp = test_client.post("/api/v1/imports/init")
        assert resp.status_code == 200
        data = resp.json()
        assert "job_id" in data

        _, SessionLocal = tmp_db
        db = SessionLocal()
        job = db.query(ImportJob).filter(ImportJob.id == data["job_id"]).first()
        assert job is not None
        assert job.status == "uploading"
        db.close()

    def test_init_creates_staging_dir(self, test_client, tmp_db, tmp_path, monkeypatch):
        """POST /init creates the staging directory."""
        staging_root = tmp_path / "staging"
        staging_root.mkdir(exist_ok=True)
        monkeypatch.setattr("backend.app.api.imports.settings.staging_dir", staging_root)

        resp = test_client.post("/api/v1/imports/init")
        assert resp.status_code == 200
        job_id = resp.json()["job_id"]
        assert (staging_root / job_id).is_dir()


# ---------------------------------------------------------------------------
# Upload with job_id tests
# ---------------------------------------------------------------------------


class TestUploadWithJobId:
    def test_upload_with_invalid_job_id(self, test_client, tmp_path, monkeypatch):
        """Upload with a nonexistent job_id returns 404."""
        staging_root = tmp_path / "staging"
        staging_root.mkdir(exist_ok=True)
        monkeypatch.setattr("backend.app.api.imports.settings.staging_dir", staging_root)

        resp = test_client.post(
            "/api/v1/imports/upload",
            data={"job_id": "nonexistent123"},
            files=[("files", ("test.jpg", b"\xff\xd8\xff\xe0" + b"\x00" * 100, "image/jpeg"))],
        )
        assert resp.status_code == 404

    def test_upload_rejects_non_uploading_job(self, test_client, tmp_db, tmp_path, monkeypatch):
        """Upload with a job not in 'uploading' status returns 409."""
        staging_root = tmp_path / "staging"
        staging_root.mkdir(exist_ok=True)
        monkeypatch.setattr("backend.app.api.imports.settings.staging_dir", staging_root)

        _, SessionLocal = tmp_db
        db = SessionLocal()
        _make_job(db, "job-staging", status="staging")
        db.commit()
        db.close()

        resp = test_client.post(
            "/api/v1/imports/job-staging/upload-batch",
            files=[("files", ("test.jpg", b"\xff\xd8\xff\xe0" + b"\x00" * 100, "image/jpeg"))],
        )
        assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Analysis endpoint tests
# ---------------------------------------------------------------------------


class TestGetAnalysis:
    def test_analysis_returns_groups(self, test_client, tmp_db):
        """GET /{job_id}/analysis returns stored analysis groups."""
        import json

        _, SessionLocal = tmp_db
        db = SessionLocal()
        analysis_data = {
            "summary": [{"group_name": "Map Pack", "author": "Author A", "file_count": 2}],
            "groups": [
                {
                    "author": "Author A",
                    "group_name": "Map Pack",
                    "files": [
                        {
                            "relative_path": "map1.jpg",
                            "filename": "map1.jpg",
                            "detected_tags": [],
                        },
                        {
                            "relative_path": "map2.jpg",
                            "filename": "map2.jpg",
                            "detected_tags": [],
                        },
                    ],
                }
            ],
        }
        job = _make_job(db, "job-with-analysis", status="staging", total_files=2)
        job.analysis_result = json.dumps(analysis_data)
        db.commit()
        db.close()

        resp = test_client.get("/api/v1/imports/job-with-analysis/analysis")
        assert resp.status_code == 200
        data = resp.json()
        assert data["job_id"] == "job-with-analysis"
        assert len(data["groups"]) == 1
        assert data["groups"][0]["group_name"] == "Map Pack"
        assert len(data["groups"][0]["files"]) == 2

    def test_analysis_404_for_uploading_job(self, test_client, tmp_db):
        """GET /analysis returns 404 for a job still uploading (no analysis yet)."""
        _, SessionLocal = tmp_db
        db = SessionLocal()
        _make_job(db, "job-uploading", status="uploading")
        db.commit()
        db.close()

        resp = test_client.get("/api/v1/imports/job-uploading/analysis")
        assert resp.status_code == 404

    def test_analysis_404_for_missing_job(self, test_client):
        """GET /analysis returns 404 for nonexistent job."""
        resp = test_client.get("/api/v1/imports/nonexistent/analysis")
        assert resp.status_code == 404

    def test_analysis_handles_legacy_format(self, test_client, tmp_db):
        """GET /analysis returns 404 for legacy analysis format (no full groups)."""
        import json

        _, SessionLocal = tmp_db
        db = SessionLocal()
        # Legacy format is a plain list without "groups" key
        legacy = [{"group_name": "G1", "author": "A", "file_count": 1}]
        job = _make_job(db, "job-legacy", status="staging")
        job.analysis_result = json.dumps(legacy)
        db.commit()
        db.close()

        resp = test_client.get("/api/v1/imports/job-legacy/analysis")
        assert resp.status_code == 404  # No full groups available

    def test_pending_groups_reflected_in_status(self, test_client, tmp_db):
        """Status endpoint reports pending_groups from DB, not analysis_result."""
        _, SessionLocal = tmp_db
        db = SessionLocal()
        job = _make_job(db, "job-newformat", status="staging", total_files=3)
        job.pending_groups = 3
        db.commit()
        db.close()

        resp = test_client.get("/api/v1/imports/job-newformat/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["detected_group_count"] == 3  # pending_groups + 0 submitted
        assert data["pending_group_count"] == 3


# ---------------------------------------------------------------------------
# POST /api/v1/imports/{job_id}/fail
# ---------------------------------------------------------------------------


class TestFailEndpoint:
    def test_fail_uploading_job(self, test_client, tmp_db):
        """Uploading job transitions to failed with error message."""
        _, SessionLocal = tmp_db
        db = SessionLocal()
        _make_job(db, "job_fail_upload", status="uploading")
        db.commit()
        db.close()

        resp = test_client.post(
            "/api/v1/imports/job_fail_upload/fail",
            json={"error_message": "Network timeout during upload"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "failed"
        assert data["error_message"] == "Network timeout during upload"

    def test_fail_staging_job(self, test_client, tmp_db):
        """Staging job transitions to failed with error message."""
        _, SessionLocal = tmp_db
        db = SessionLocal()
        _make_job(db, "job_fail_staging", status="staging")
        db.commit()
        db.close()

        resp = test_client.post(
            "/api/v1/imports/job_fail_staging/fail",
            json={"error_message": "Analysis failed: corrupt file"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "failed"

    def test_fail_active_job_rejected(self, test_client, tmp_db):
        """Active jobs cannot use /fail — they have running groups."""
        _, SessionLocal = tmp_db
        db = SessionLocal()
        _make_job(db, "job_fail_active", status="active")
        db.commit()
        db.close()

        resp = test_client.post(
            "/api/v1/imports/job_fail_active/fail",
            json={"error_message": "Should not work"},
        )
        assert resp.status_code == 409

    def test_fail_completed_job_rejected(self, test_client, tmp_db):
        """Terminal jobs cannot use /fail."""
        _, SessionLocal = tmp_db
        db = SessionLocal()
        _make_job(db, "job_fail_done", status="completed")
        db.commit()
        db.close()

        resp = test_client.post(
            "/api/v1/imports/job_fail_done/fail",
            json={"error_message": "Nope"},
        )
        assert resp.status_code == 409

    def test_fail_nonexistent_job(self, test_client):
        resp = test_client.post(
            "/api/v1/imports/nope/fail",
            json={"error_message": "Gone"},
        )
        assert resp.status_code == 404

    def test_fail_cleans_staging(self, test_client, tmp_db, tmp_path, monkeypatch):
        """Failing a job removes its staging directory."""
        from backend.app import config

        staging_root = tmp_path / "staging"
        staging_root.mkdir(exist_ok=True)
        monkeypatch.setattr(config.settings, "staging_dir", staging_root)

        _, SessionLocal = tmp_db
        db = SessionLocal()
        _make_job(db, "job_fail_cleanup", status="uploading")
        db.commit()
        db.close()

        # Create fake staging dir
        (staging_root / "job_fail_cleanup").mkdir()
        assert (staging_root / "job_fail_cleanup").exists()

        resp = test_client.post(
            "/api/v1/imports/job_fail_cleanup/fail",
            json={"error_message": "Upload broken"},
        )
        assert resp.status_code == 200
        assert not (staging_root / "job_fail_cleanup").exists()
