"""Unit tests for maintenance helper functions.

Tests rotate_backups() and cleanup_stale_staging() as pure functions.
The backup_sqlite and full backup_database functions are already covered by
test_backup_restore.py (integration test).
"""

import os
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.models.database import Base, ImportGroupJob, ImportJob
from backend.pipeline.maintenance import (
    cleanup_stale_staging,
    mark_interrupted_jobs,
    rotate_backups,
)

# ---------------------------------------------------------------------------
# rotate_backups
# ---------------------------------------------------------------------------


def _make_backup_dir(root: Path, name: str) -> Path:
    """Create an empty backup directory with the given name."""
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    return d


class TestRotateBackups:
    def test_empty_root_returns_zero(self, tmp_path):
        root = tmp_path / "backups"
        root.mkdir()
        result = rotate_backups(root)
        assert result == 0

    def test_nonexistent_root_returns_zero(self, tmp_path):
        result = rotate_backups(tmp_path / "no_such_dir")
        assert result == 0

    def test_keeps_most_recent_n_backups(self, tmp_path):
        root = tmp_path / "backups"
        root.mkdir()
        # Create 5 backups in chronological order
        names = [
            "20240101_000000",
            "20240102_000000",
            "20240103_000000",
            "20240104_000000",
            "20240105_000000",
        ]
        for name in names:
            _make_backup_dir(root, name)

        deleted = rotate_backups(root, keep_daily=3, keep_weekly=0)

        # 5 created, 3 kept → 2 deleted
        assert deleted == 2
        remaining = {d.name for d in root.iterdir() if d.is_dir()}
        # Most recent 3 should survive
        assert "20240103_000000" in remaining
        assert "20240104_000000" in remaining
        assert "20240105_000000" in remaining

    def test_invalid_dirname_format_is_left_alone(self, tmp_path):
        """Directories that don't match YYYYMMDD_HHMMSS format are skipped."""
        root = tmp_path / "backups"
        root.mkdir()
        # Enough valid dirs to trigger rotation
        for i in range(10):
            _make_backup_dir(root, f"2024010{i}_120000" if i < 10 else "20240110_120000")
        # Add one with an invalid name
        invalid = _make_backup_dir(root, "unknown_backup_dir")

        rotate_backups(root, keep_daily=3, keep_weekly=1)

        # Invalid-name dir must still be there
        assert invalid.exists()

    def test_weekly_retention_keeps_one_per_week(self, tmp_path):
        root = tmp_path / "backups"
        root.mkdir()
        # Create 14 daily backups — 2 weeks worth
        for day in range(1, 15):
            _make_backup_dir(
                root, f"20240{day:02d}01_000000" if day <= 9 else f"20241{day - 9:02d}01_000000"
            )

        deleted = rotate_backups(root, keep_daily=3, keep_weekly=2)
        remaining = list(root.iterdir())
        # keep_daily=3 + keep_weekly=2 → at most 5 kept, rest deleted
        assert deleted >= 1
        assert len(remaining) <= 5

    def test_all_fit_in_keep_daily_nothing_deleted(self, tmp_path):
        root = tmp_path / "backups"
        root.mkdir()
        _make_backup_dir(root, "20240101_000000")
        _make_backup_dir(root, "20240102_000000")

        deleted = rotate_backups(root, keep_daily=7, keep_weekly=4)
        assert deleted == 0


# ---------------------------------------------------------------------------
# cleanup_stale_staging
# ---------------------------------------------------------------------------


class TestCleanupStaleStaging:
    def test_nonexistent_staging_root_returns_zero(self, tmp_path, monkeypatch):
        mock_settings = MagicMock()
        mock_settings.staging_dir = tmp_path / "no_staging_here"
        monkeypatch.setattr("backend.pipeline.maintenance.settings", mock_settings)

        result = cleanup_stale_staging(max_age_hours=24)
        assert result == 0

    def test_empty_staging_root_returns_zero(self, tmp_path, monkeypatch):
        staging = tmp_path / "staging"
        staging.mkdir()
        mock_settings = MagicMock()
        mock_settings.staging_dir = staging
        monkeypatch.setattr("backend.pipeline.maintenance.settings", mock_settings)

        result = cleanup_stale_staging(max_age_hours=24)
        assert result == 0

    def test_fresh_dir_not_deleted(self, tmp_path, monkeypatch):
        staging = tmp_path / "staging"
        staging.mkdir()
        fresh_dir = staging / "fresh_job"
        fresh_dir.mkdir()
        # mtime is now — definitely within 24h

        mock_settings = MagicMock()
        mock_settings.staging_dir = staging
        monkeypatch.setattr("backend.pipeline.maintenance.settings", mock_settings)

        result = cleanup_stale_staging(max_age_hours=24)
        assert result == 0
        assert fresh_dir.exists()

    def test_stale_dir_is_deleted(self, tmp_path, monkeypatch):
        staging = tmp_path / "staging"
        staging.mkdir()
        stale_dir = staging / "stale_job"
        stale_dir.mkdir()

        # Back-date the mtime to 48h ago
        two_days_ago = time.time() - 48 * 3600
        os.utime(stale_dir, (two_days_ago, two_days_ago))

        mock_settings = MagicMock()
        mock_settings.staging_dir = staging
        monkeypatch.setattr("backend.pipeline.maintenance.settings", mock_settings)

        result = cleanup_stale_staging(max_age_hours=24)
        assert result == 1
        assert not stale_dir.exists()

    def test_mix_of_stale_and_fresh(self, tmp_path, monkeypatch):
        staging = tmp_path / "staging"
        staging.mkdir()

        stale = staging / "stale_job"
        stale.mkdir()
        two_days_ago = time.time() - 48 * 3600
        os.utime(stale, (two_days_ago, two_days_ago))

        fresh = staging / "fresh_job"
        fresh.mkdir()
        # fresh has current mtime

        mock_settings = MagicMock()
        mock_settings.staging_dir = staging
        monkeypatch.setattr("backend.pipeline.maintenance.settings", mock_settings)

        result = cleanup_stale_staging(max_age_hours=24)
        assert result == 1
        assert not stale.exists()
        assert fresh.exists()

    def test_non_directory_entries_ignored(self, tmp_path, monkeypatch):
        """Files (not dirs) inside staging root are left alone."""
        staging = tmp_path / "staging"
        staging.mkdir()
        a_file = staging / "somefile.txt"
        a_file.write_text("data")

        mock_settings = MagicMock()
        mock_settings.staging_dir = staging
        monkeypatch.setattr("backend.pipeline.maintenance.settings", mock_settings)

        result = cleanup_stale_staging(max_age_hours=24)
        assert result == 0
        assert a_file.exists()


# ---------------------------------------------------------------------------
# mark_interrupted_jobs
# ---------------------------------------------------------------------------


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _make_import_job(db, job_id, status):
    job = ImportJob(id=job_id, status=status, total_files=1)
    db.add(job)
    db.flush()
    return job


def _make_import_group(db, job_id, group_id, status="running"):
    gj = ImportGroupJob(
        id=group_id,
        job_id=job_id,
        group_name="G",
        author="A",
        total_files=1,
        processed_files=0,
        failed_files=0,
        status=status,
    )
    db.add(gj)
    db.flush()
    return gj


class TestMarkInterruptedJobs:
    def test_active_job_becomes_broken(self, db_session):
        _make_import_job(db_session, "j1", "active")
        count = mark_interrupted_jobs(db_session)
        db_session.commit()
        job = db_session.query(ImportJob).filter_by(id="j1").first()
        assert job.status == "broken"
        assert count == 1

    def test_uploading_job_becomes_broken(self, db_session):
        _make_import_job(db_session, "j1", "uploading")
        mark_interrupted_jobs(db_session)
        db_session.commit()
        assert db_session.query(ImportJob).filter_by(id="j1").first().status == "broken"

    def test_running_groups_marked_failed(self, db_session):
        _make_import_job(db_session, "j1", "active")
        _make_import_group(db_session, "j1", "g1", "running")
        _make_import_group(db_session, "j1", "g2", "completed")
        mark_interrupted_jobs(db_session)
        db_session.commit()
        g1 = db_session.query(ImportGroupJob).filter_by(id="g1").first()
        g2 = db_session.query(ImportGroupJob).filter_by(id="g2").first()
        assert g1.status == "failed"
        assert g2.status == "completed"  # already terminal, not changed

    def test_staging_job_becomes_broken(self, db_session):
        _make_import_job(db_session, "j1", "staging")
        mark_interrupted_jobs(db_session)
        db_session.commit()
        assert db_session.query(ImportJob).filter_by(id="j1").first().status == "broken"

    def test_awaiting_input_unchanged(self, db_session):
        _make_import_job(db_session, "j1", "awaiting_input")
        mark_interrupted_jobs(db_session)
        assert db_session.query(ImportJob).filter_by(id="j1").first().status == "awaiting_input"

    def test_completed_job_unchanged(self, db_session):
        _make_import_job(db_session, "j1", "completed")
        mark_interrupted_jobs(db_session)
        assert db_session.query(ImportJob).filter_by(id="j1").first().status == "completed"

    def test_error_message_set(self, db_session):
        _make_import_job(db_session, "j1", "active")
        mark_interrupted_jobs(db_session)
        db_session.commit()
        job = db_session.query(ImportJob).filter_by(id="j1").first()
        assert "restarted" in (job.error_message or "").lower()

    def test_completed_at_set(self, db_session):
        _make_import_job(db_session, "j1", "uploading")
        mark_interrupted_jobs(db_session)
        db_session.commit()
        job = db_session.query(ImportJob).filter_by(id="j1").first()
        assert job.completed_at is not None

    def test_no_interrupted_jobs_returns_zero(self, db_session):
        _make_import_job(db_session, "j1", "completed")
        _make_import_job(db_session, "j2", "awaiting_input")
        count = mark_interrupted_jobs(db_session)
        assert count == 0

    def test_multiple_interrupted_jobs_all_marked(self, db_session):
        _make_import_job(db_session, "j1", "active")
        _make_import_job(db_session, "j2", "uploading")
        count = mark_interrupted_jobs(db_session)
        db_session.commit()
        assert count == 2
        assert db_session.query(ImportJob).filter_by(id="j1").first().status == "broken"
        assert db_session.query(ImportJob).filter_by(id="j2").first().status == "broken"
