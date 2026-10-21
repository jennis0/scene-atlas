"""Tests for two-root config split (SCENE_ATLAS_DATA_DIR + SCENE_ATLAS_IMAGES_DIR)."""

import pytest

from backend.app.config import Settings


class TestConfigDefaults:
    def test_both_roots_accepted_as_kwargs(self, tmp_path):
        (tmp_path / "data").mkdir()
        (tmp_path / "images").mkdir()
        s = Settings(data_dir=tmp_path / "data", images_dir=tmp_path / "images")
        assert s.data_dir == tmp_path / "data"
        assert s.images_dir == tmp_path / "images"

    def test_derived_paths_from_app_data_dir(self, tmp_path):
        (tmp_path / "data").mkdir()
        (tmp_path / "images").mkdir()
        s = Settings(data_dir=tmp_path / "data", images_dir=tmp_path / "images")
        assert s.store_thumbnails_dir == tmp_path / "data" / "store" / "thumbnails"
        assert s.staging_dir == tmp_path / "data" / "staging"
        assert s.vector_db_path == tmp_path / "data" / "lancedb"

    def test_image_store_is_flat_under_image_library(self, tmp_path):
        (tmp_path / "data").mkdir()
        (tmp_path / "images").mkdir()
        s = Settings(data_dir=tmp_path / "data", images_dir=tmp_path / "images")
        assert s.store_images_dir == tmp_path / "images"

    def test_backups_under_image_library(self, tmp_path):
        (tmp_path / "data").mkdir()
        (tmp_path / "images").mkdir()
        s = Settings(data_dir=tmp_path / "data", images_dir=tmp_path / "images")
        assert s.backups_dir == tmp_path / "images" / "backups"

    def test_env_override_recomputes_derived_paths(self, monkeypatch, tmp_path):
        (tmp_path / "fast").mkdir()
        (tmp_path / "slow").mkdir()
        monkeypatch.setenv("SCENE_ATLAS_DATA_DIR", str(tmp_path / "fast"))
        monkeypatch.setenv("SCENE_ATLAS_IMAGES_DIR", str(tmp_path / "slow"))
        s = Settings()
        assert s.store_thumbnails_dir == tmp_path / "fast" / "store" / "thumbnails"
        assert s.store_images_dir == tmp_path / "slow"
        assert s.backups_dir == tmp_path / "slow" / "backups"

    def test_database_url_uses_app_data_dir(self, tmp_path):
        (tmp_path / "data").mkdir()
        (tmp_path / "images").mkdir()
        s = Settings(data_dir=tmp_path / "data", images_dir=tmp_path / "images")
        assert str(tmp_path / "data" / "battlemap.db") in s.database_url

    def test_derived_values_ignore_env(self, monkeypatch, tmp_path):
        """Derived paths come only from the roots; env vars cannot override them."""
        (tmp_path / "data").mkdir()
        monkeypatch.setenv("DATABASE_URL", "sqlite:////elsewhere.db")
        monkeypatch.setenv("STAGING_DIR", str(tmp_path / "elsewhere"))
        s = Settings(data_dir=tmp_path / "data", images_dir=tmp_path / "images")
        assert s.database_url == f"sqlite:///{tmp_path / 'data' / 'battlemap.db'}"
        assert s.staging_dir == tmp_path / "data" / "staging"


class TestStartupValidation:
    def test_raises_if_app_data_dir_missing(self, tmp_path):
        (tmp_path / "images").mkdir()
        with pytest.raises(ValueError, match="SCENE_ATLAS_DATA_DIR"):
            Settings(
                data_dir=tmp_path / "nonexistent",
                images_dir=tmp_path / "images",
                validate_roots=True,
            )

    def test_raises_if_image_library_dir_missing(self, tmp_path):
        (tmp_path / "data").mkdir()
        with pytest.raises(ValueError, match="SCENE_ATLAS_IMAGES_DIR"):
            Settings(
                data_dir=tmp_path / "data",
                images_dir=tmp_path / "nonexistent",
                validate_roots=True,
            )

    def test_no_raise_when_roots_exist(self, tmp_path):
        (tmp_path / "data").mkdir()
        (tmp_path / "images").mkdir()
        # Should not raise
        Settings(
            data_dir=tmp_path / "data",
            images_dir=tmp_path / "images",
            validate_roots=True,
        )

    def test_subdirs_created_within_roots(self, tmp_path):
        (tmp_path / "data").mkdir()
        (tmp_path / "images").mkdir()
        s = Settings(data_dir=tmp_path / "data", images_dir=tmp_path / "images")
        assert s.store_thumbnails_dir.exists()
        assert s.staging_dir.exists()
        assert s.vector_db_path.exists()


class TestImageLibraryDefault:
    """With only SCENE_ATLAS_DATA_DIR set, a library stays in one place."""

    @pytest.fixture(autouse=True)
    def _no_roots_in_env(self, monkeypatch):
        monkeypatch.delenv("SCENE_ATLAS_DATA_DIR", raising=False)
        monkeypatch.delenv("SCENE_ATLAS_IMAGES_DIR", raising=False)

    def test_library_goes_inside_the_data_dir(self, tmp_path):
        s = Settings(data_dir=tmp_path)
        assert s.images_dir == tmp_path / "images"
        assert s.store_images_dir == tmp_path / "images"

    def test_from_the_environment_too(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SCENE_ATLAS_DATA_DIR", str(tmp_path))
        assert Settings().images_dir == tmp_path / "images"

    def test_explicit_library_wins(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SCENE_ATLAS_DATA_DIR", str(tmp_path / "data"))
        monkeypatch.setenv("SCENE_ATLAS_IMAGES_DIR", str(tmp_path / "library"))
        assert Settings().images_dir == tmp_path / "library"

    def test_existing_library_keeps_its_old_location(self, tmp_path):
        from backend.app.config import _LEGACY_LIBRARY_DIR

        (tmp_path / "battlemap.db").touch()  # made before the default changed
        assert Settings(data_dir=tmp_path).images_dir == _LEGACY_LIBRARY_DIR
        (tmp_path / "images").mkdir()  # moved beside the data
        assert Settings(data_dir=tmp_path).images_dir == tmp_path / "images"

    def test_development_default_is_unchanged(self):
        from backend.app.config import _LEGACY_LIBRARY_DIR

        # Ignore a developer's own .env
        assert Settings(_env_file=None).images_dir == _LEGACY_LIBRARY_DIR


class TestLinkedLibraryDir:
    def test_from_env_and_need_not_exist(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SCENE_ATLAS_LINKED_LIBRARY_DIR", str(tmp_path / "Battle Maps"))
        assert Settings(data_dir=tmp_path).linked_library_dir == tmp_path / "Battle Maps"

    def test_empty_env_is_unset(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SCENE_ATLAS_LINKED_LIBRARY_DIR", " ")
        assert Settings(data_dir=tmp_path).linked_library_dir is None


class TestEnvNames:
    """Every variable is read with the SCENE_ATLAS_ prefix, and only with it (ADR-027)."""

    def test_prefixed_names_are_read(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SCENE_ATLAS_DEBUG", "true")
        monkeypatch.setenv("SCENE_ATLAS_DATA_DIR", str(tmp_path / "data"))
        monkeypatch.setenv("SCENE_ATLAS_IMAGES_DIR", str(tmp_path / "images"))
        s = Settings(_env_file=None)
        assert s.debug is True
        assert s.data_dir == tmp_path / "data"
        assert s.images_dir == tmp_path / "images"

    def test_unprefixed_and_field_names_are_ignored(self, monkeypatch, tmp_path):
        for name in ("DEBUG", "SCENE_ATLAS_DEBUG"):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("SCENE_ATLAS_DATA_DIR", str(tmp_path / "data"))
        monkeypatch.setenv("DEBUG", "true")
        monkeypatch.setenv("IMAGE_LIBRARY_DIR", str(tmp_path / "old"))
        monkeypatch.setenv("SCENE_ATLAS_IMAGE_LIBRARY_DIR", str(tmp_path / "field"))
        monkeypatch.delenv("SCENE_ATLAS_IMAGES_DIR", raising=False)
        s = Settings(_env_file=None)
        assert s.debug is False
        assert s.images_dir == tmp_path / "data" / "images"
