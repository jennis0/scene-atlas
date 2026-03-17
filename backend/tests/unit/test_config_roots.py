"""Tests for two-root config split (APP_DATA_DIR + IMAGE_LIBRARY_DIR)."""

import pytest

from backend.app.config import Settings


class TestConfigDefaults:
    def test_both_roots_accepted_as_kwargs(self, tmp_path):
        (tmp_path / "data").mkdir()
        (tmp_path / "images").mkdir()
        s = Settings(app_data_dir=tmp_path / "data", image_library_dir=tmp_path / "images")
        assert s.app_data_dir == tmp_path / "data"
        assert s.image_library_dir == tmp_path / "images"

    def test_derived_paths_from_app_data_dir(self, tmp_path):
        (tmp_path / "data").mkdir()
        (tmp_path / "images").mkdir()
        s = Settings(app_data_dir=tmp_path / "data", image_library_dir=tmp_path / "images")
        assert s.store_thumbnails_dir == tmp_path / "data" / "store" / "thumbnails"
        assert s.staging_dir == tmp_path / "data" / "staging"
        assert s.vector_db_path == tmp_path / "data" / "lancedb"
        assert s.config_dir == tmp_path / "data" / "config"

    def test_image_store_is_flat_under_image_library(self, tmp_path):
        (tmp_path / "data").mkdir()
        (tmp_path / "images").mkdir()
        s = Settings(app_data_dir=tmp_path / "data", image_library_dir=tmp_path / "images")
        assert s.store_images_dir == tmp_path / "images"

    def test_backups_under_image_library(self, tmp_path):
        (tmp_path / "data").mkdir()
        (tmp_path / "images").mkdir()
        s = Settings(app_data_dir=tmp_path / "data", image_library_dir=tmp_path / "images")
        assert s.backups_dir == tmp_path / "images" / "backups"

    def test_env_override_recomputes_derived_paths(self, monkeypatch, tmp_path):
        (tmp_path / "fast").mkdir()
        (tmp_path / "slow").mkdir()
        monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "fast"))
        monkeypatch.setenv("IMAGE_LIBRARY_DIR", str(tmp_path / "slow"))
        s = Settings()
        assert s.store_thumbnails_dir == tmp_path / "fast" / "store" / "thumbnails"
        assert s.store_images_dir == tmp_path / "slow"
        assert s.backups_dir == tmp_path / "slow" / "backups"

    def test_database_url_uses_app_data_dir(self, tmp_path):
        (tmp_path / "data").mkdir()
        (tmp_path / "images").mkdir()
        s = Settings(app_data_dir=tmp_path / "data", image_library_dir=tmp_path / "images")
        assert str(tmp_path / "data" / "battlemap.db") in s.database_url


class TestStartupValidation:
    def test_raises_if_app_data_dir_missing(self, tmp_path):
        (tmp_path / "images").mkdir()
        with pytest.raises(ValueError, match="APP_DATA_DIR"):
            Settings(
                app_data_dir=tmp_path / "nonexistent",
                image_library_dir=tmp_path / "images",
                validate_roots=True,
            )

    def test_raises_if_image_library_dir_missing(self, tmp_path):
        (tmp_path / "data").mkdir()
        with pytest.raises(ValueError, match="IMAGE_LIBRARY_DIR"):
            Settings(
                app_data_dir=tmp_path / "data",
                image_library_dir=tmp_path / "nonexistent",
                validate_roots=True,
            )

    def test_no_raise_when_roots_exist(self, tmp_path):
        (tmp_path / "data").mkdir()
        (tmp_path / "images").mkdir()
        # Should not raise
        Settings(
            app_data_dir=tmp_path / "data",
            image_library_dir=tmp_path / "images",
            validate_roots=True,
        )

    def test_subdirs_created_within_roots(self, tmp_path):
        (tmp_path / "data").mkdir()
        (tmp_path / "images").mkdir()
        s = Settings(app_data_dir=tmp_path / "data", image_library_dir=tmp_path / "images")
        assert s.store_thumbnails_dir.exists()
        assert s.staging_dir.exists()
        assert s.vector_db_path.exists()
        assert s.config_dir.exists()
