"""Integration tests: upload-batch and analyse endpoints.

Tests the two-step upload flow:
  POST /api/v1/imports/                      -- create job (returns job_id)
  POST /api/v1/imports/{job_id}/upload-batch -- stage files
  POST /api/v1/imports/{job_id}/analyse      -- run group detection

The JobRunner.run_sync is mocked so analysis returns fake groups without
requiring real CLIP/grid-detection infrastructure.
"""

import json
import zipfile
from io import BytesIO
from unittest.mock import MagicMock

import pytest
from PIL import Image as PILImage


def _make_jpeg_bytes(width=20, height=20, color=(100, 150, 200)):
    """Create minimal valid JPEG bytes in memory."""
    img = PILImage.new("RGB", (width, height), color)
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=70)
    buf.seek(0)
    return buf.read()


def _fake_groups(author="TestAuthor", group_name="TestMap", filename="map.jpg"):
    """Return a fake analyse_upload result (list of group dicts)."""
    return [
        {
            "author": author,
            "group_name": group_name,
            "files": [
                {
                    "relative_path": f"{author}/{group_name}/{filename}",
                    "parsed": {
                        "filename": filename,
                        "author": author,
                        "group_name": group_name,
                        "tags": [],
                        "gridded": None,
                        "grid_width": None,
                        "grid_height": None,
                        "subgroup": None,
                    },
                }
            ],
        }
    ]


@pytest.fixture
def upload_env(test_client, monkeypatch):
    """Mock the JobRunner for analyse calls and expose the staging dir.

    Relies on the test_client fixture to have already redirected
    settings.staging_dir to an isolated tmp directory.  Returns
    (staging_base, client, mock_runner).
    """
    from backend.app.config import settings

    staging_base = settings.staging_dir  # already redirected by test_client fixture

    mock_runner = MagicMock()
    mock_runner.run_sync.return_value = _fake_groups()
    monkeypatch.setattr("backend.app.api.imports.get_job_runner", lambda: mock_runner)

    return staging_base, test_client, mock_runner


# ---------------------------------------------------------------------------
# Helper: create a job via the init endpoint
# ---------------------------------------------------------------------------


def _init_job(client):
    """POST /api/v1/imports/init and return the job_id."""
    resp = client.post("/api/v1/imports/init")
    assert resp.status_code == 200, resp.text
    return resp.json()["job_id"]


# ---------------------------------------------------------------------------
# upload-batch tests
# ---------------------------------------------------------------------------


class TestUploadBatch:
    """POST /api/v1/imports/{job_id}/upload-batch"""

    def test_single_valid_image(self, upload_env):
        """Single valid JPEG is saved to staging; response reports one file saved."""
        staging_base, client, _ = upload_env
        job_id = _init_job(client)
        jpeg = _make_jpeg_bytes()

        resp = client.post(
            f"/api/v1/imports/{job_id}/upload-batch",
            files=[("files", ("map.jpg", jpeg, "image/jpeg"))],
            data={"relative_paths": json.dumps(["TestAuthor/TestMap/map.jpg"])},
        )

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["files_saved"] == 1
        assert data["bytes_saved"] > 0
        assert data["skipped_invalid"] == []

        # File must exist in staging
        saved = staging_base / job_id / "TestAuthor" / "TestMap" / "map.jpg"
        assert saved.exists()

    def test_multiple_files_in_one_batch(self, upload_env):
        """Multiple valid files upload in a single batch."""
        _, client, _ = upload_env
        job_id = _init_job(client)
        jpeg1 = _make_jpeg_bytes(color=(255, 0, 0))
        jpeg2 = _make_jpeg_bytes(color=(0, 255, 0))

        resp = client.post(
            f"/api/v1/imports/{job_id}/upload-batch",
            files=[
                ("files", ("map1.jpg", jpeg1, "image/jpeg")),
                ("files", ("map2.jpg", jpeg2, "image/jpeg")),
            ],
        )

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["files_saved"] == 2

    def test_invalid_file_skipped_and_reported(self, upload_env):
        """A file with wrong magic bytes is skipped; its name appears in skipped_invalid."""
        _, client, _ = upload_env
        job_id = _init_job(client)
        fake_exe = b"MZ" + b"\x00" * 200  # Windows PE magic bytes, extension is .jpg

        resp = client.post(
            f"/api/v1/imports/{job_id}/upload-batch",
            files=[("files", ("malware.jpg", fake_exe, "image/jpeg"))],
        )

        # Endpoint does not fail — it skips the bad file and reports it
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["files_saved"] == 0
        assert "malware.jpg" in data["skipped_invalid"]

    def test_file_exceeds_size_limit_rejected(self, upload_env, monkeypatch):
        """A file larger than max_import_file_size returns 413."""
        from backend.app.models.schemas import AppSettings

        monkeypatch.setattr(
            "backend.app.api.imports.get_app_settings",
            lambda db: AppSettings(max_import_file_size=100),
        )
        _, client, _ = upload_env
        job_id = _init_job(client)
        jpeg = _make_jpeg_bytes()  # ~1 KB, well over 100-byte limit

        resp = client.post(
            f"/api/v1/imports/{job_id}/upload-batch",
            files=[("files", ("big.jpg", jpeg, "image/jpeg"))],
        )

        assert resp.status_code == 413, resp.text
        assert "size limit" in resp.json()["detail"]

    def test_nonexistent_job_returns_404(self, upload_env):
        """upload-batch with an unknown job_id returns 404."""
        _, client, _ = upload_env
        jpeg = _make_jpeg_bytes()

        resp = client.post(
            "/api/v1/imports/doesnotexist/upload-batch",
            files=[("files", ("map.jpg", jpeg, "image/jpeg"))],
        )

        assert resp.status_code == 404, resp.text

    def test_wrong_status_job_returns_409(self, upload_env, tmp_db):
        """upload-batch against a job not in 'uploading' status returns 409."""
        from backend.app.models import ImportJob

        _, client, _ = upload_env
        _, SessionLocal = tmp_db
        db = SessionLocal()
        db.add(ImportJob(id="staged-job", status="staging", total_files=0))
        db.commit()
        db.close()

        jpeg = _make_jpeg_bytes()
        resp = client.post(
            "/api/v1/imports/staged-job/upload-batch",
            files=[("files", ("map.jpg", jpeg, "image/jpeg"))],
        )

        assert resp.status_code == 409, resp.text

    def test_zip_file_extracted_to_staging(self, upload_env):
        """A valid ZIP containing an image is extracted into the staging directory."""
        staging_base, client, _ = upload_env
        job_id = _init_job(client)

        # Build a ZIP with one valid JPEG inside
        jpeg = _make_jpeg_bytes()
        zip_buf = BytesIO()
        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_STORED) as zf:
            zf.writestr("Author/Map/scene.jpg", jpeg)
        zip_bytes = zip_buf.getvalue()

        resp = client.post(
            f"/api/v1/imports/{job_id}/upload-batch",
            files=[("files", ("scenes.zip", zip_bytes, "application/zip"))],
        )

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["files_saved"] == 1
        # The extracted file should exist in staging
        extracted = staging_base / job_id / "Author" / "Map" / "scene.jpg"
        assert extracted.exists()


# ---------------------------------------------------------------------------
# analyse tests
# ---------------------------------------------------------------------------


class TestAnalyse:
    """POST /api/v1/imports/{job_id}/analyse"""

    def test_single_file_analyse_succeeds(self, upload_env):
        """Upload one file then analyse; returns groups with correct shape."""
        staging_base, client, _ = upload_env
        job_id = _init_job(client)
        jpeg = _make_jpeg_bytes()

        # Stage the file first
        client.post(
            f"/api/v1/imports/{job_id}/upload-batch",
            files=[("files", ("map.jpg", jpeg, "image/jpeg"))],
            data={"relative_paths": json.dumps(["TestAuthor/TestMap/map.jpg"])},
        )

        resp = client.post(
            f"/api/v1/imports/{job_id}/analyse",
            json={"image_type": "battlemap", "manifest": []},
        )

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "job_id" in data
        assert data["job_id"] == job_id
        assert data["total_files"] >= 1
        assert len(data["groups"]) == 1
        # ImageParser CamelCase-splits directory names: "TestMap" → "Test Map"
        assert data["groups"][0]["group_name"] == "Test Map"

    def test_multiple_files_analyse_succeeds(self, upload_env):
        """Upload files in two distinct group directories; analyse detects two groups."""
        _, client, _ = upload_env
        job_id = _init_job(client)
        jpeg1 = _make_jpeg_bytes(color=(255, 0, 0))
        jpeg2 = _make_jpeg_bytes(color=(0, 255, 0))

        # Upload each file with a path that places it in a different group directory
        client.post(
            f"/api/v1/imports/{job_id}/upload-batch",
            files=[("files", ("a.jpg", jpeg1, "image/jpeg"))],
            data={"relative_paths": json.dumps(["AuthorA/Map1/a.jpg"])},
        )
        client.post(
            f"/api/v1/imports/{job_id}/upload-batch",
            files=[("files", ("b.jpg", jpeg2, "image/jpeg"))],
            data={"relative_paths": json.dumps(["AuthorB/Map2/b.jpg"])},
        )

        resp = client.post(
            f"/api/v1/imports/{job_id}/analyse",
            json={"image_type": "battlemap", "manifest": []},
        )

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert len(data["groups"]) == 2

    def test_analyse_nonexistent_job_returns_404(self, upload_env):
        """analyse on an unknown job_id returns 404."""
        _, client, _ = upload_env

        resp = client.post(
            "/api/v1/imports/doesnotexist/analyse",
            json={"image_type": "battlemap", "manifest": []},
        )

        assert resp.status_code == 404, resp.text

    def test_analyse_wrong_status_returns_409(self, upload_env, tmp_db):
        """analyse on a job not in 'uploading' status returns 409."""
        from backend.app.models import ImportJob

        _, client, _ = upload_env
        _, SessionLocal = tmp_db
        db = SessionLocal()
        db.add(ImportJob(id="staged-job2", status="staging", total_files=0))
        db.commit()
        db.close()

        resp = client.post(
            "/api/v1/imports/staged-job2/analyse",
            json={"image_type": "battlemap", "manifest": []},
        )

        assert resp.status_code == 409, resp.text

    def test_invalid_image_type_rejected(self, upload_env):
        """analyse with an invalid image_type returns 400."""
        _, client, _ = upload_env
        job_id = _init_job(client)
        jpeg = _make_jpeg_bytes()

        # Stage one file so staging dir exists and has content
        client.post(
            f"/api/v1/imports/{job_id}/upload-batch",
            files=[("files", ("map.jpg", jpeg, "image/jpeg"))],
            data={"relative_paths": json.dumps(["map.jpg"])},
        )

        resp = client.post(
            f"/api/v1/imports/{job_id}/analyse",
            json={"image_type": "invalid_type", "manifest": []},
        )

        assert resp.status_code == 400, resp.text
        assert "Invalid image_type" in resp.json()["detail"]
