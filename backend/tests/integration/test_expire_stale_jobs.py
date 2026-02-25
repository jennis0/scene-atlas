"""Integration tests for expire_stale_jobs maintenance task.

Tests the scheduled task that marks abandoned import jobs as expired
and cleans up their staging directories.
"""

from datetime import UTC, datetime, timedelta

import pytest

from backend.app.models.database import ImportGroupJob, ImportJob


@pytest.fixture
def _patch_db_for_expiry(monkeypatch, tmp_db, tmp_path):
    """Point settings at the test DB and temp staging dir."""
    engine, SessionLocal = tmp_db
    monkeypatch.setattr("backend.app.config.settings.database_url", str(engine.url))
    monkeypatch.setattr("backend.app.config.settings.staging_dir", tmp_path / "staging")
    (tmp_path / "staging").mkdir(exist_ok=True)
    return engine, SessionLocal, tmp_path / "staging"


class TestExpireStaleJobs:
    def test_expires_old_staging_job(self, _patch_db_for_expiry):
        """A staging job older than max_age_hours is expired."""
        from backend.pipeline.maintenance import expire_stale_jobs

        engine, SessionLocal, staging_root = _patch_db_for_expiry

        db = SessionLocal()
        old_time = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=72)
        job = ImportJob(
            id="old-staging-job",
            status="staging",
            total_files=1,
            created_at=old_time,
            updated_at=old_time,
        )
        db.add(job)
        db.commit()
        db.close()

        # Create staging dir
        job_staging = staging_root / "old-staging-job"
        job_staging.mkdir()
        (job_staging / "test.txt").write_text("data")

        result = expire_stale_jobs(max_age_hours=48)
        assert result["expired"] == 1

        db = SessionLocal()
        job = db.query(ImportJob).filter(ImportJob.id == "old-staging-job").first()
        assert job.status == "expired"
        assert job.completed_at is not None
        db.close()

        # Staging should be cleaned
        assert not job_staging.exists()

    def test_expires_old_active_job(self, _patch_db_for_expiry):
        """An active job with no recent activity is expired."""
        from backend.pipeline.maintenance import expire_stale_jobs

        engine, SessionLocal, staging_root = _patch_db_for_expiry

        db = SessionLocal()
        old_time = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=72)
        job = ImportJob(
            id="old-active-job",
            status="active",
            total_files=3,
            created_at=old_time,
            updated_at=old_time,
        )
        db.add(job)
        db.flush()
        # One completed group, but the job was abandoned before the rest were submitted
        db.add(
            ImportGroupJob(
                id="grp-old",
                job_id="old-active-job",
                group_name="Map A",
                author="Author",
                total_files=1,
                processed_files=1,
                status="completed",
            )
        )
        db.commit()
        db.close()

        result = expire_stale_jobs(max_age_hours=48)
        assert result["expired"] == 1

        db = SessionLocal()
        job = db.query(ImportJob).filter(ImportJob.id == "old-active-job").first()
        assert job.status == "expired"
        db.close()

    def test_preserves_recent_job(self, _patch_db_for_expiry):
        """A job with recent activity is not expired."""
        from backend.pipeline.maintenance import expire_stale_jobs

        engine, SessionLocal, staging_root = _patch_db_for_expiry

        db = SessionLocal()
        recent_time = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1)
        job = ImportJob(
            id="recent-job",
            status="active",
            total_files=2,
            created_at=recent_time,
            updated_at=recent_time,
        )
        db.add(job)
        db.commit()
        db.close()

        result = expire_stale_jobs(max_age_hours=48)
        assert result["expired"] == 0

        db = SessionLocal()
        job = db.query(ImportJob).filter(ImportJob.id == "recent-job").first()
        assert job.status == "active"
        db.close()

    def test_preserves_job_with_running_groups(self, _patch_db_for_expiry):
        """A stale job with running groups is NOT expired (would kill in-progress work)."""
        from backend.pipeline.maintenance import expire_stale_jobs

        engine, SessionLocal, staging_root = _patch_db_for_expiry

        db = SessionLocal()
        old_time = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=72)
        job = ImportJob(
            id="running-groups-job",
            status="active",
            total_files=2,
            created_at=old_time,
            updated_at=old_time,
        )
        db.add(job)
        db.flush()
        db.add(
            ImportGroupJob(
                id="grp-running",
                job_id="running-groups-job",
                group_name="Map A",
                author="Author",
                total_files=1,
                status="running",
            )
        )
        db.commit()
        db.close()

        result = expire_stale_jobs(max_age_hours=48)
        assert result["expired"] == 0

        db = SessionLocal()
        job = db.query(ImportJob).filter(ImportJob.id == "running-groups-job").first()
        assert job.status == "active"  # unchanged
        db.close()

    def test_does_not_expire_completed_jobs(self, _patch_db_for_expiry):
        """Already-terminal jobs are not touched."""
        from backend.pipeline.maintenance import expire_stale_jobs

        engine, SessionLocal, staging_root = _patch_db_for_expiry

        db = SessionLocal()
        old_time = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=72)
        job = ImportJob(
            id="completed-job",
            status="completed",
            total_files=1,
            created_at=old_time,
            updated_at=old_time,
            completed_at=old_time,
        )
        db.add(job)
        db.commit()
        db.close()

        result = expire_stale_jobs(max_age_hours=48)
        assert result["expired"] == 0
