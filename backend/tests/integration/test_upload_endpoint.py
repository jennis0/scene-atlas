"""Integration test: upload endpoint.

Tests POST /api/v1/imports/upload.
Mocks run_deployment (Prefect) — the endpoint saves files to staging,
then calls analyse_upload via Prefect deployment.
"""

import json
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from PIL import Image as PILImage


def _make_jpeg_bytes(width=20, height=20, color=(100, 150, 200)):
    """Create minimal JPEG bytes in memory."""
    img = PILImage.new("RGB", (width, height), color)
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=70)
    buf.seek(0)
    return buf.read()


@pytest.fixture
def _setup_upload(tmp_path, tmp_db, monkeypatch):
    """Mock run_deployment to return fake analysis results."""
    staging_base = tmp_path / "staging"
    staging_base.mkdir(parents=True)
    monkeypatch.setattr("backend.app.config.settings.staging_dir", staging_base)

    # Build a mock flow run that returns analysis groups
    mock_state = MagicMock()
    mock_state.is_failed.return_value = False

    async def fake_result():
        return [
            {
                "author": "TestAuthor",
                "variant_group_name": "TestMap",
                "files": [
                    {
                        "relative_path": "TestAuthor/TestMap/map.jpg",
                        "parsed": {
                            "filename": "map.jpg",
                            "author": "TestAuthor",
                            "variant_group_name": "TestMap",
                            "tags": [],
                            "gridded": None,
                            "grid_width": None,
                            "grid_height": None,
                            "sub_variant": None,
                        },
                    }
                ],
            }
        ]

    mock_state.result = fake_result
    mock_flow_run = MagicMock()
    mock_flow_run.state = mock_state

    mock_run_deployment = AsyncMock(return_value=mock_flow_run)
    monkeypatch.setattr("backend.app.api.imports.run_deployment", mock_run_deployment)

    return staging_base, mock_run_deployment


class TestUploadEndpoint:
    """Upload files endpoint."""

    def test_upload_single_file(self, test_client, _setup_upload):
        staging_base, mock_run = _setup_upload
        jpeg_data = _make_jpeg_bytes()

        resp = test_client.post(
            "/api/v1/imports/upload",
            files=[("files", ("map.jpg", jpeg_data, "image/jpeg"))],
            data={"relative_paths": json.dumps(["TestAuthor/TestMap/map.jpg"])},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert "job_id" in data
        assert data["total_files"] == 1
        assert len(data["variant_groups"]) == 1
        assert data["variant_groups"][0]["variant_group_name"] == "TestMap"

        # Verify file was saved to staging
        job_id = data["job_id"]
        saved = staging_base / job_id / "TestAuthor" / "TestMap" / "map.jpg"
        assert saved.exists()

    def test_upload_unsupported_format_filtered(self, test_client, _setup_upload):
        """Non-image files should be filtered out."""
        staging_base, _ = _setup_upload
        resp = test_client.post(
            "/api/v1/imports/upload",
            files=[("files", ("doc.pdf", b"fake pdf content", "application/pdf"))],
        )
        assert resp.status_code == 400  # No supported files

    def test_upload_multiple_files(self, test_client, _setup_upload):
        staging_base, _ = _setup_upload
        jpeg1 = _make_jpeg_bytes(color=(255, 0, 0))
        jpeg2 = _make_jpeg_bytes(color=(0, 255, 0))

        resp = test_client.post(
            "/api/v1/imports/upload",
            files=[
                ("files", ("map1.jpg", jpeg1, "image/jpeg")),
                ("files", ("map2.jpg", jpeg2, "image/jpeg")),
            ],
        )
        assert resp.status_code == 200
