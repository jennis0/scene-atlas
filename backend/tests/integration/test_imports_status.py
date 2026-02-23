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
    """One ImportJob + one running ImportGroupJob."""
    _, SessionLocal = tmp_db
    db = SessionLocal()
    _make_job(db, "jobrunninga", status="running", total_files=3)
    _make_group_job(db, "jobrunninga", "grp001", status="running", processed=1, total=3)
    db.commit()
    db.close()
    yield test_client, "jobrunninga", "grp001"


@pytest.fixture
def seeded_completed_job(test_client, tmp_db):
    """One ImportJob + one completed ImportGroupJob (completed very recently)."""
    _, SessionLocal = tmp_db
    db = SessionLocal()
    _make_job(db, "jobdonebb", status="completed", total_files=2)
    _make_group_job(
        db,
        "jobdonebb",
        "grp002",
        status="completed",
        processed=2,
        total=2,
        completed_at=datetime.now(UTC).replace(tzinfo=None),
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

    def test_running_job_with_group(self, seeded_running_job):
        client, job_id, grp_id = seeded_running_job
        resp = client.get(f"/api/v1/imports/{job_id}/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "running"
        assert len(data["groups"]) == 1
        assert data["groups"][0]["status"] == "running"
        assert data["groups"][0]["processed_files"] == 1

    def test_all_groups_terminal_shows_completed(self, seeded_completed_job):
        client, job_id = seeded_completed_job
        resp = client.get(f"/api/v1/imports/{job_id}/status")
        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"

    def test_mixed_terminal_status_shows_failed(self, test_client, tmp_db):
        _, SessionLocal = tmp_db
        db = SessionLocal()
        _make_job(db, "jobmixedcc", status="running", total_files=4)
        _make_group_job(db, "jobmixedcc", "grp_ok", status="completed", processed=2, total=2)
        _make_group_job(
            db, "jobmixedcc", "grp_fail", group_name="FailGroup", status="failed", total=2
        )
        db.commit()
        db.close()

        resp = test_client.get("/api/v1/imports/jobmixedcc/status")
        assert resp.status_code == 200
        # All groups terminal + one failed → completed (status endpoint just returns "completed"
        # for all-terminal; the failed distinction is on individual groups)
        data = resp.json()
        assert data["status"] == "completed"
        statuses = {g["group_name"]: g["status"] for g in data["groups"]}
        assert statuses["FailGroup"] == "failed"


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
    def test_cleanup_removes_staging_job(self, seeded_job):
        client, job_id = seeded_job
        resp = client.delete("/api/v1/imports/cleanup")
        assert resp.status_code == 200
        assert resp.json()["deleted"] >= 1
        # Job should no longer be in active
        active_ids = [j["job_id"] for j in client.get("/api/v1/imports/active").json()["jobs"]]
        assert job_id not in active_ids

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

    def test_cancel_all_terminal_groups_sets_completed(self, test_client, tmp_db):
        _, SessionLocal = tmp_db
        db = SessionLocal()
        _make_job(db, "jobtermeee", status="running", total_files=2)
        _make_group_job(db, "jobtermeee", "grp_t1", status="completed", total=1)
        _make_group_job(db, "jobtermeee", "grp_t2", group_name="Grp2", status="failed", total=1)
        db.commit()
        db.close()

        resp = test_client.post("/api/v1/imports/jobtermeee/cancel")
        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"


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
