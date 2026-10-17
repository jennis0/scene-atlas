"""Unit tests for backend.app.services.model_download_service."""

import errno
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestIsModelDownloaded:
    def test_returns_false_when_no_version_json(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "backend.app.services.model_download_service._settings",
            _make_settings(tmp_path),
        )
        from backend.app.services.model_download_service import is_model_downloaded

        assert is_model_downloaded("small") is False

    def test_returns_true_when_version_json_present(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "backend.app.services.model_download_service._settings",
            _make_settings(tmp_path),
        )
        _write_version_json(tmp_path, "small")

        from backend.app.services.model_download_service import is_model_downloaded

        assert is_model_downloaded("small") is True

    def test_returns_false_for_different_model(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "backend.app.services.model_download_service._settings",
            _make_settings(tmp_path),
        )
        _write_version_json(tmp_path, "small")

        from backend.app.services.model_download_service import is_model_downloaded

        # "medium" version.json is absent
        assert is_model_downloaded("medium") is False


class TestGetVersionInfo:
    def test_returns_none_when_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "backend.app.services.model_download_service._settings",
            _make_settings(tmp_path),
        )
        from backend.app.services.model_download_service import get_version_info

        assert get_version_info("small") is None

    def test_returns_dict_when_version_json_present(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "backend.app.services.model_download_service._settings",
            _make_settings(tmp_path),
        )
        _write_version_json(tmp_path, "small", sha="abc123")

        from backend.app.services.model_download_service import get_version_info

        info = get_version_info("small")
        assert isinstance(info, dict)
        assert info["hf_commit_sha"] == "abc123"
        assert "downloaded_at" in info

    def test_returns_none_on_corrupt_json(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "backend.app.services.model_download_service._settings",
            _make_settings(tmp_path),
        )
        model_dir = tmp_path / "models" / "small"
        model_dir.mkdir(parents=True, exist_ok=True)
        (model_dir / "version.json").write_text("not valid json", encoding="utf-8")

        from backend.app.services.model_download_service import get_version_info

        assert get_version_info("small") is None


class TestDownloadModel:
    def test_raises_model_download_error_on_unknown_name(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "backend.app.services.model_download_service._settings",
            _make_settings(tmp_path),
        )
        from backend.app.services.model_download_service import (
            ModelDownloadError,
            download_model,
        )

        with pytest.raises(ModelDownloadError, match="Unknown model"):
            download_model("does_not_exist")

    def test_raises_on_hf_http_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "backend.app.services.model_download_service._settings",
            _make_settings(tmp_path),
        )

        from huggingface_hub.utils import HfHubHTTPError

        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.headers = {}

        # The service does `from huggingface_hub import model_info as hf_model_info`
        # inside the function body, so we patch huggingface_hub.model_info directly.
        with patch(
            "huggingface_hub.model_info",
            side_effect=HfHubHTTPError("403 Forbidden", response=mock_response),
        ):
            from backend.app.services.model_download_service import (
                ModelDownloadError,
                download_model,
            )

            with pytest.raises(ModelDownloadError):
                download_model("small")

    def test_raises_on_connection_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "backend.app.services.model_download_service._settings",
            _make_settings(tmp_path),
        )

        import requests

        with patch(
            "huggingface_hub.model_info",
            side_effect=requests.exceptions.ConnectionError("network unreachable"),
        ):
            from backend.app.services.model_download_service import (
                ModelDownloadError,
                download_model,
            )

            with pytest.raises(ModelDownloadError, match="HuggingFace|connect"):
                download_model("small")

    def test_raises_on_connection_error_during_download(self, tmp_path, monkeypatch):
        """ConnectionError raised by snapshot_download (Phase 2) should raise ModelDownloadError.

        This exercises the _raise_download_error() ConnectionError branch, which is distinct
        from the existing test that patches model_info (Phase 1) to raise ConnectionError.
        """
        monkeypatch.setattr(
            "backend.app.services.model_download_service._settings",
            _make_settings(tmp_path),
        )

        import requests

        mock_info = MagicMock()
        mock_info.sha = "abc123"

        with (
            patch("huggingface_hub.model_info", return_value=mock_info),
            patch(
                "huggingface_hub.snapshot_download",
                side_effect=requests.exceptions.ConnectionError("Connection refused"),
            ),
        ):
            from backend.app.services.model_download_service import (
                ModelDownloadError,
                download_model,
            )

            with pytest.raises(ModelDownloadError, match="HuggingFace|connect"):
                download_model("small")

    def test_writes_version_json_after_success(self, tmp_path, monkeypatch):
        """version.json is the completion marker — written after all required files."""
        monkeypatch.setattr(
            "backend.app.services.model_download_service._settings",
            _make_settings(tmp_path),
        )

        mock_info = MagicMock()
        mock_info.sha = "deadbeef1234"

        def fake_snapshot_download(repo_id, local_dir, **kwargs):
            # Simulate what a real download would do
            dest = Path(local_dir)
            dest.mkdir(parents=True, exist_ok=True)
            (dest / "manifest.json").write_text("{}", encoding="utf-8")
            (dest / "clip_vision_encoder.onnx").write_bytes(b"fake-onnx")
            (dest / "clip_text_encoder.onnx").write_bytes(b"fake-onnx")

        with (
            patch("huggingface_hub.model_info", return_value=mock_info),
            patch(
                "huggingface_hub.snapshot_download",
                side_effect=fake_snapshot_download,
            ),
        ):
            from backend.app.services.model_download_service import (
                download_model,
                get_model_dir,
                is_model_downloaded,
            )

            # "large" is still published with the bundle at the repo root
            result = download_model("large")

        # version.json must exist (completion marker)
        model_dir = get_model_dir("large")
        assert (model_dir / "version.json").exists()
        assert is_model_downloaded("large") is True

        # Return value should include sha and name
        assert result["name"] == "large"
        assert result["hf_commit_sha"] == "deadbeef1234"
        assert "downloaded_at" in result

    def test_subfolder_model_downloads_only_the_bundle(self, tmp_path, monkeypatch):
        """Repos with hf_subfolder hold a training checkpoint at the root: fetch only the
        subfolder, pinned to hf_revision, and install its contents as the model dir."""
        monkeypatch.setattr(
            "backend.app.services.model_download_service._settings",
            _make_settings(tmp_path),
        )
        mock_info = MagicMock()
        mock_info.sha = "cafef00d5678"
        calls = {}

        def fake_snapshot_download(repo_id, local_dir, **kwargs):
            calls.update(kwargs)
            bundle = Path(local_dir) / "onnx"
            (bundle / "tokenizer").mkdir(parents=True, exist_ok=True)
            (bundle / "manifest.json").write_text("{}", encoding="utf-8")
            (bundle / "clip_vision_encoder.onnx").write_bytes(b"fake-onnx")
            (bundle / "clip_text_encoder.onnx").write_bytes(b"fake-onnx")
            (bundle / "tokenizer" / "tokenizer.json").write_text("{}", encoding="utf-8")

        with (
            patch("huggingface_hub.model_info", return_value=mock_info) as info,
            patch("huggingface_hub.snapshot_download", side_effect=fake_snapshot_download),
        ):
            from backend.app.services.model_download_service import download_model, get_model_dir
            from backend.app.services.model_registry import get_model

            entry = get_model("medium")
            download_model("medium")

        assert calls["allow_patterns"] == ["onnx/*"]
        assert calls["revision"] == entry["hf_revision"]
        assert info.call_args.kwargs["revision"] == entry["hf_revision"]
        model_dir = get_model_dir("medium")
        assert (model_dir / "manifest.json").exists()
        assert (model_dir / "tokenizer" / "tokenizer.json").exists()
        assert not (model_dir / "onnx").exists()
        version = json.loads((model_dir / "version.json").read_text())
        assert version["hf_revision"] == entry["hf_revision"]

    def test_version_json_not_written_on_missing_files(self, tmp_path, monkeypatch):
        """If required files are absent after snapshot_download, version.json must NOT be written."""
        monkeypatch.setattr(
            "backend.app.services.model_download_service._settings",
            _make_settings(tmp_path),
        )

        mock_info = MagicMock()
        mock_info.sha = "abc"

        def fake_snapshot_download_incomplete(repo_id, local_dir, **kwargs):
            # Only creates manifest.json — missing the ONNX files
            dest = Path(local_dir)
            dest.mkdir(parents=True, exist_ok=True)
            (dest / "manifest.json").write_text("{}", encoding="utf-8")
            # Intentionally NOT creating the .onnx files

        with (
            patch("huggingface_hub.model_info", return_value=mock_info),
            patch(
                "huggingface_hub.snapshot_download",
                side_effect=fake_snapshot_download_incomplete,
            ),
        ):
            from backend.app.services.model_download_service import (
                ModelDownloadError,
                download_model,
                get_model_dir,
            )

            with pytest.raises(ModelDownloadError, match="incomplete"):
                download_model("small")

        # version.json must NOT exist after a failed download
        model_dir = get_model_dir("small")
        assert not (model_dir / "version.json").exists()


class TestCheckDiskSpace:
    def test_returns_ok_when_enough_space(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "backend.app.services.model_download_service._settings",
            _make_settings(tmp_path),
        )
        # Mock disk_usage to report plenty of free space (10 GB)
        mock_usage = MagicMock()
        mock_usage.free = 10 * 1024 * 1024 * 1024  # 10 GB
        with patch("shutil.disk_usage", return_value=mock_usage):
            from backend.app.services.model_download_service import check_disk_space

            ok, needed_mb, available_mb = check_disk_space("small")
        assert ok is True
        assert needed_mb > 0
        assert available_mb > needed_mb

    def test_returns_not_ok_when_low_space(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "backend.app.services.model_download_service._settings",
            _make_settings(tmp_path),
        )
        # Mock disk_usage to report only 10 MB free (not enough for any model)
        mock_usage = MagicMock()
        mock_usage.free = 10 * 1024 * 1024  # 10 MB
        with patch("shutil.disk_usage", return_value=mock_usage):
            from backend.app.services.model_download_service import check_disk_space

            ok, needed_mb, available_mb = check_disk_space("small")
        assert ok is False
        assert available_mb == 10
        assert needed_mb > available_mb

    def test_raises_on_unknown_model(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "backend.app.services.model_download_service._settings",
            _make_settings(tmp_path),
        )
        from backend.app.services.model_download_service import (
            ModelDownloadError,
            check_disk_space,
        )

        with pytest.raises(ModelDownloadError, match="Unknown model"):
            check_disk_space("nonexistent_model")

    def test_applies_multiplier(self, tmp_path, monkeypatch):
        """Needed MB should be approx_size_mb * 1.5."""
        monkeypatch.setattr(
            "backend.app.services.model_download_service._settings",
            _make_settings(tmp_path),
        )
        mock_usage = MagicMock()
        mock_usage.free = 100 * 1024 * 1024 * 1024
        with patch("shutil.disk_usage", return_value=mock_usage):
            from backend.app.services.model_download_service import check_disk_space
            from backend.app.services.model_registry import get_model

            _, needed_mb, _ = check_disk_space("small")
        # the registry's approximate size, multiplied by 1.5
        assert needed_mb == int(get_model("small")["approx_size_mb"] * 1.5)


class TestDownloadModelDiskSpacePreCheck:
    def test_raises_on_insufficient_disk_space(self, tmp_path, monkeypatch):
        """download_model() should fail early if disk space is insufficient."""
        monkeypatch.setattr(
            "backend.app.services.model_download_service._settings",
            _make_settings(tmp_path),
        )
        mock_usage = MagicMock()
        mock_usage.free = 10 * 1024 * 1024  # 10 MB — too little
        with patch("shutil.disk_usage", return_value=mock_usage):
            from backend.app.services.model_download_service import (
                ModelDownloadError,
                download_model,
            )

            with pytest.raises(ModelDownloadError, match="Insufficient disk space"):
                download_model("small")


class TestRaiseDownloadErrorMapping:
    """Tests for specific error type mappings in _raise_download_error."""

    def test_timeout_error_gives_user_friendly_message(self):
        import requests

        from backend.app.services.model_download_service import (
            ModelDownloadError,
            _raise_download_error,
        )

        with pytest.raises(ModelDownloadError, match="timed out"):
            _raise_download_error(requests.exceptions.Timeout("timed out"), "repo/test")

    def test_connection_error_gives_user_friendly_message(self):
        import requests

        from backend.app.services.model_download_service import (
            ModelDownloadError,
            _raise_download_error,
        )

        with pytest.raises(ModelDownloadError, match="Could not connect"):
            _raise_download_error(requests.exceptions.ConnectionError("refused"), "repo/test")

    def test_permission_error_gives_user_friendly_message(self):
        from backend.app.services.model_download_service import (
            ModelDownloadError,
            _raise_download_error,
        )

        with pytest.raises(ModelDownloadError, match="permissions"):
            _raise_download_error(PermissionError("denied"), "repo/test")

    def test_enospc_gives_disk_space_message(self):
        from backend.app.services.model_download_service import (
            ModelDownloadError,
            _raise_download_error,
        )

        exc = OSError(errno.ENOSPC, "No space left on device")
        with pytest.raises(ModelDownloadError, match="disk space"):
            _raise_download_error(exc, "repo/test")

    def test_generic_oserror_gives_filesystem_message(self):
        from backend.app.services.model_download_service import (
            ModelDownloadError,
            _raise_download_error,
        )

        exc = OSError(errno.EIO, "I/O error")
        with pytest.raises(ModelDownloadError, match="File system error"):
            _raise_download_error(exc, "repo/test")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(data_dir: Path):
    """Return a minimal settings mock with app_data_dir pointing at tmp_path."""
    settings = MagicMock()
    settings.app_data_dir = data_dir
    return settings


def _write_version_json(data_dir: Path, name: str, sha: str = "sha123") -> Path:
    """Create a minimal version.json for a model under data_dir/models/{name}/."""
    model_dir = data_dir / "models" / name
    model_dir.mkdir(parents=True, exist_ok=True)
    version_data = {"hf_commit_sha": sha, "downloaded_at": "2026-01-01T00:00:00+00:00"}
    (model_dir / "version.json").write_text(json.dumps(version_data, indent=2), encoding="utf-8")
    return model_dir / "version.json"
