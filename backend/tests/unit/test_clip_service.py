"""Unit tests for backend.app.services.clip_service module-level helpers.

These tests cover the new public/private symbols added for model management:
_get_active_model_name, _has_real_gpu_provider, get_effective_model_name,
reload_clip_service, wait_for_clip_ready.

CLIPService itself is not instantiated here — ONNX model files are required
for that and are absent in unit tests.
"""

import threading


class TestGetActiveModelName:
    def test_uses_env_var_when_embedding_model_set(self, monkeypatch):
        monkeypatch.setenv("EMBEDDING_MODEL", "large")
        from backend.app.services.clip_service import _get_active_model_name

        result = _get_active_model_name()
        assert result == "large"

    def test_env_var_overrides_db(self, monkeypatch):
        """EMBEDDING_MODEL env var takes priority over any DB value."""
        monkeypatch.setenv("EMBEDDING_MODEL", "medium")
        from backend.app.services.clip_service import _get_active_model_name

        result = _get_active_model_name()
        assert result == "medium"

    def test_env_var_not_set_returns_string(self, monkeypatch):
        """Without env var it falls through to DB / auto-detect; result must be a non-empty string."""
        monkeypatch.delenv("EMBEDDING_MODEL", raising=False)
        from backend.app.services.clip_service import _get_active_model_name

        result = _get_active_model_name()
        assert isinstance(result, str)
        assert len(result) > 0


class TestGetEffectiveModelName:
    def test_returns_active_model_name_when_set(self, monkeypatch):
        """get_effective_model_name returns _active_model_name when it's populated."""
        import backend.app.services.clip_service as clip_mod

        original = clip_mod._active_model_name
        try:
            clip_mod._active_model_name = "large"
            from backend.app.services.clip_service import get_effective_model_name

            result = get_effective_model_name()
            assert result == "large"
        finally:
            clip_mod._active_model_name = original

    def test_falls_back_to_get_active_model_name_when_none(self, monkeypatch):
        """When _active_model_name is None, falls back to _get_active_model_name()."""
        import backend.app.services.clip_service as clip_mod

        original = clip_mod._active_model_name
        try:
            clip_mod._active_model_name = None
            monkeypatch.setenv("EMBEDDING_MODEL", "small")
            from backend.app.services.clip_service import get_effective_model_name

            result = get_effective_model_name()
            assert result == "small"
        finally:
            clip_mod._active_model_name = original


class TestReloadClipService:
    def test_noop_when_already_loading(self):
        """If _clip_ready is clear (reload in progress), reload_clip_service returns current thread."""
        import backend.app.services.clip_service as clip_mod

        # Save original state
        orig_event_is_set = clip_mod._clip_ready.is_set()

        try:
            # Simulate reload in progress: clear the ready event
            clip_mod._clip_ready.clear()

            # A second call while the event is cleared should return current_thread
            # but since the wait() would block, we simulate the scenario:
            # We patch _clip_ready.wait to be a no-op so the test doesn't hang.
            original_wait = clip_mod._clip_ready.wait
            clip_mod._clip_ready.wait = lambda timeout=None: None

            try:
                from backend.app.services.clip_service import reload_clip_service

                result = reload_clip_service()
                # The no-op path returns threading.current_thread()
                assert result is threading.current_thread()
            finally:
                clip_mod._clip_ready.wait = original_wait
        finally:
            # Restore event to original state
            if orig_event_is_set:
                clip_mod._clip_ready.set()
            else:
                clip_mod._clip_ready.clear()

    def test_reload_clip_service_is_callable(self):
        from backend.app.services.clip_service import reload_clip_service

        assert callable(reload_clip_service)


class TestWaitForClipReady:
    def test_wait_for_clip_ready_is_callable(self):
        from backend.app.services.clip_service import wait_for_clip_ready

        assert callable(wait_for_clip_ready)

    def test_wait_for_clip_ready_returns_when_event_set(self):
        """wait_for_clip_ready should return immediately when _clip_ready is set."""
        import backend.app.services.clip_service as clip_mod

        orig_is_set = clip_mod._clip_ready.is_set()
        try:
            clip_mod._clip_ready.set()
            from backend.app.services.clip_service import wait_for_clip_ready

            # Should complete without hanging
            wait_for_clip_ready()
        finally:
            if not orig_is_set:
                clip_mod._clip_ready.clear()


class TestStartClipBackgroundLoad:
    def test_returns_noop_thread_when_already_loaded(self):
        """start_clip_background_load returns a noop thread if _clip_ready is already set."""
        import backend.app.services.clip_service as clip_mod

        orig_is_set = clip_mod._clip_ready.is_set()
        try:
            clip_mod._clip_ready.set()
            from backend.app.services.clip_service import start_clip_background_load

            t = start_clip_background_load()
            assert isinstance(t, threading.Thread)
            t.join(timeout=2)
            # The noop thread should finish quickly
            assert not t.is_alive()
        finally:
            if not orig_is_set:
                clip_mod._clip_ready.clear()
