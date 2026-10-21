"""Unit tests for app_mode config (backend/app/config.py).

Verifies that the SCENE_ATLAS_APP_MODE environment variable controls the mode field.
"""

from backend.app.config import Settings


class TestAppMode:
    def test_default_mode_is_server(self, monkeypatch):
        """Without SCENE_ATLAS_APP_MODE env var, mode should default to 'server'."""
        monkeypatch.delenv("SCENE_ATLAS_APP_MODE", raising=False)
        s = Settings()
        assert s.app_mode == "server"

    def test_app_mode_from_env(self, monkeypatch):
        """SCENE_ATLAS_APP_MODE=app should be picked up by pydantic-settings."""
        monkeypatch.setenv("SCENE_ATLAS_APP_MODE", "app")
        s = Settings()
        assert s.app_mode == "app"
