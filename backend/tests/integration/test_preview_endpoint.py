"""Integration test: preview thumbnail serving endpoint.

Tests the GET /api/v1/imports/{job_id}/preview/{relative_path} endpoint.
Uses real filesystem (no DB needed for this endpoint).
"""

import json

import pytest


@pytest.fixture
def staged_with_thumbs(tmp_path, make_test_image, monkeypatch):
    """Create a staging dir with flat UUID files, thumbnails, and file_map."""
    job_id = "preview-test-job"
    staging_base = tmp_path / "staging"
    staging_dir = staging_base / job_id
    staging_dir.mkdir(parents=True, exist_ok=True)

    # Create original image as flat UUID-named file
    staging_key = "bbbb0001.jpg"
    make_test_image(staging_dir / staging_key, color=(50, 100, 150))

    # Create thumbnail keyed by staging_key stem
    thumbs_dir = staging_dir / ".thumbs"
    thumbs_dir.mkdir(parents=True)
    make_test_image(thumbs_dir / "bbbb0001.jpg", width=120, height=120, color=(50, 100, 150))

    # Write file map
    file_map = {"author/map.jpg": staging_key}
    (staging_dir / ".file_map.json").write_text(json.dumps(file_map))

    # Point settings.staging_dir at our tmp_path
    monkeypatch.setattr("backend.app.config.settings.staging_dir", staging_base)

    return job_id, staging_dir


class TestPreviewEndpoint:
    """Preview thumbnail serving."""

    def test_thumbnail_served(self, test_client, staged_with_thumbs):
        job_id, _ = staged_with_thumbs
        resp = test_client.get(f"/api/v1/imports/{job_id}/preview/author/map.jpg")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/jpeg"

    def test_fallback_to_original(self, test_client, staged_with_thumbs, make_test_image):
        """When no thumbnail exists, serve the original file."""
        job_id, staging_dir = staged_with_thumbs
        # Create an image without a corresponding thumbnail
        staging_key = "bbbb0002.png"
        make_test_image(staging_dir / staging_key, color=(200, 50, 50))
        # Update file map
        file_map = json.loads((staging_dir / ".file_map.json").read_text())
        file_map["other/file.png"] = staging_key
        (staging_dir / ".file_map.json").write_text(json.dumps(file_map))

        resp = test_client.get(f"/api/v1/imports/{job_id}/preview/other/file.png")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/png"

    def test_missing_file_returns_404(self, test_client, staged_with_thumbs):
        job_id, _ = staged_with_thumbs
        resp = test_client.get(f"/api/v1/imports/{job_id}/preview/nonexistent/file.jpg")
        assert resp.status_code == 404

    def test_nonexistent_job_returns_404(self, test_client, staged_with_thumbs):
        resp = test_client.get("/api/v1/imports/no-such-job/preview/file.jpg")
        assert resp.status_code == 404

    def test_path_traversal_blocked(self, test_client, staged_with_thumbs):
        """Relative paths with ../ must be rejected (not in file_map → 404)."""
        job_id, _ = staged_with_thumbs
        resp = test_client.get(f"/api/v1/imports/{job_id}/preview/../../../etc/passwd")
        assert resp.status_code in (403, 404)
