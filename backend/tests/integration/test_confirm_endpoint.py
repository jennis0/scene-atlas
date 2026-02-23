"""Integration test: confirm import endpoint.

Tests POST /api/v1/imports/{job_id}/confirm.
Mocks JobRunner.submit — we only check that the endpoint validates
input, submits the job with correct params, and updates the DB.
"""

from unittest.mock import MagicMock

import pytest

from backend.app.models import ImportJob


@pytest.fixture
def confirm_env(tmp_path, tmp_db, make_test_image, monkeypatch):
    """Set up staging dir, DB, and mock JobRunner. Return client + job_id + mock."""
    from fastapi.testclient import TestClient

    from backend.app.main import app

    job_id = "confirm-test-job"
    staging_base = tmp_path / "staging"
    staging_dir = staging_base / job_id

    make_test_image(staging_dir / "author" / "map.jpg")
    make_test_image(staging_dir / "author" / "map2.jpg")

    monkeypatch.setattr("backend.app.config.settings.staging_dir", staging_base)

    # Mock JobRunner so submit() is a no-op that returns a fake job ID
    mock_runner = MagicMock()
    mock_runner.submit.return_value = "fake-job-id"
    monkeypatch.setattr("backend.app.api.imports.get_job_runner", lambda: mock_runner)

    engine, SessionLocal = tmp_db

    # Create TestClient first (runs lifespan), then override db_engine
    with TestClient(app, raise_server_exceptions=False) as client:
        app.state.db_engine = engine

        # Create ImportJob in the test DB
        db = SessionLocal()
        job = ImportJob(id=job_id, status="staging", total_files=2)
        db.add(job)
        db.commit()
        db.close()

        yield client, job_id, mock_runner


class TestConfirmEndpoint:
    """Confirm import endpoint."""

    def test_confirm_success(self, confirm_env):
        client, job_id, mock_runner = confirm_env
        resp = client.post(
            f"/api/v1/imports/{job_id}/confirm",
            json={
                "author": "TestAuthor",
                "group_name": "Test Map",
                "files": [
                    {
                        "relative_path": "author/map.jpg",
                        "tags": [{"category": "lighting", "value": "night"}],
                        "gridded": True,
                        "grid_width": 30,
                        "grid_height": 30,
                        "subgroup": "Night",
                    },
                ],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "running"
        assert data["job_id"] == job_id

        # Verify JobRunner.submit was called with correct params
        mock_runner.submit.assert_called_once()
        call_args = mock_runner.submit.call_args
        # First positional arg is the function, rest are kwargs
        assert call_args.kwargs["author"] == "TestAuthor"
        assert call_args.kwargs["group_name"] == "Test Map"
        assert len(call_args.kwargs["files"]) == 1
        assert call_args.kwargs["files"][0]["tags"][0]["category"] == "lighting"

    def test_confirm_nonexistent_job(self, confirm_env):
        client, _, _ = confirm_env
        resp = client.post(
            "/api/v1/imports/no-such-job/confirm",
            json={
                "author": "A",
                "group_name": "G",
                "files": [{"relative_path": "f.jpg"}],
            },
        )
        assert resp.status_code == 404

    def test_confirm_no_valid_files(self, confirm_env):
        """All files are missing from staging → 400."""
        client, job_id, _ = confirm_env
        resp = client.post(
            f"/api/v1/imports/{job_id}/confirm",
            json={
                "author": "A",
                "group_name": "G",
                "files": [{"relative_path": "nonexistent/file.jpg"}],
            },
        )
        assert resp.status_code == 400
