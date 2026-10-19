"""Unit tests for backend.app.services.clip_service module-level helpers.

These tests cover the new public/private symbols added for model management:
_get_active_model_name, _has_real_gpu_provider, get_effective_model_name,
reload_clip_service, wait_for_clip_ready.

CLIPService is only instantiated here without model files (the not-downloaded
path): loading one needs ONNX model files, which unit tests don't have.
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
    def test_noop_when_already_loading(self, monkeypatch):
        """If _clip_ready is clear (reload in progress), reload_clip_service:
        - returns threading.current_thread() (no-op sentinel)
        - does NOT call start_clip_background_load
        """
        import backend.app.services.clip_service as clip_mod

        # Simulate a reload already in progress: clear the ready event so the
        # "already loading" branch is taken.
        clip_mod._clip_ready.clear()

        # Patch wait() so it doesn't block (simulates the in-progress reload
        # completing instantly from the caller's perspective).
        monkeypatch.setattr(clip_mod._clip_ready, "wait", lambda timeout=None: None)

        # Track whether start_clip_background_load is called.
        started = []
        monkeypatch.setattr(
            clip_mod,
            "start_clip_background_load",
            lambda: started.append(True) or threading.Thread(target=lambda: None),
        )

        try:
            from backend.app.services.clip_service import reload_clip_service

            result = reload_clip_service()
            # The "already loading" branch returns threading.current_thread()
            assert result is threading.current_thread()
            # No new background thread should have been started
            assert started == [], (
                "start_clip_background_load should NOT be called when already loading"
            )
        finally:
            # Restore ready event so other tests are not affected
            clip_mod._clip_ready.set()

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


class TestModelNotDownloaded:
    def test_missing_files_raise_file_not_found(self, tmp_path):
        """Checked before ONNX Runtime, whose NoSuchFile _load_clip() would count as a failure."""
        import pytest

        from backend.app.services.clip_service import CLIPService

        with pytest.raises(FileNotFoundError, match="not downloaded"):
            CLIPService(models_dir=tmp_path, device="cpu")

    def test_load_without_a_model_is_not_an_error(self, tmp_path, monkeypatch):
        import backend.app.services.clip_service as clip_mod

        monkeypatch.setattr(clip_mod, "_default_models_dir", lambda: tmp_path)
        monkeypatch.setattr(clip_mod, "_clip_service", None)
        monkeypatch.setattr(clip_mod, "_clip_error", None)
        monkeypatch.setattr(clip_mod, "_clip_ready", threading.Event())

        clip_mod._load_clip()

        assert clip_mod._clip_ready.is_set()
        assert clip_mod._clip_service is None
        assert clip_mod._clip_error is None


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


class TestCastFeedToInputs:
    """Float inputs are cast to whatever dtype the ONNX graph declares."""

    def _session(self, input_type: str):
        from types import SimpleNamespace

        return SimpleNamespace(
            get_inputs=lambda: [SimpleNamespace(name="pixel_values", type=input_type)]
        )

    def test_float32_pixels_cast_for_fp16_graph(self):
        import numpy as np

        from backend.app.services.clip_service import _cast_feed_to_inputs

        feed = {"pixel_values": np.zeros((1, 3, 4, 4), np.float32)}
        out = _cast_feed_to_inputs(self._session("tensor(float16)"), feed)
        assert out["pixel_values"].dtype == np.float16

    def test_matching_and_non_float_inputs_untouched(self):
        import numpy as np

        from backend.app.services.clip_service import _cast_feed_to_inputs

        px = np.zeros((1, 3, 4, 4), np.float32)
        ids = np.zeros((1, 8), np.int64)
        out = _cast_feed_to_inputs(
            self._session("tensor(float)"), {"pixel_values": px, "input_ids": ids}
        )
        assert out["pixel_values"] is px and out["input_ids"] is ids


class TestToRgb:
    def test_transparent_pixels_become_white(self):
        from PIL import Image

        from backend.app.services.clip_service import _to_rgb

        img = Image.new("RGBA", (4, 4), (0, 0, 0, 0))  # transparent black
        img.putpixel((0, 0), (255, 0, 0, 255))
        out = _to_rgb(img)
        assert out.mode == "RGB"
        assert out.getpixel((1, 1)) == (255, 255, 255)
        assert out.getpixel((0, 0)) == (255, 0, 0)

    def test_palette_transparency_and_greyscale_alpha(self):
        from PIL import Image

        from backend.app.services.clip_service import _to_rgb

        pal = Image.new("P", (2, 2), 0)
        pal.putpalette([0, 0, 0, 10, 20, 30] + [0] * 762)
        pal.info["transparency"] = 0
        assert _to_rgb(pal).getpixel((0, 0)) == (255, 255, 255)
        assert _to_rgb(Image.new("LA", (2, 2), (0, 0))).getpixel((0, 0)) == (255, 255, 255)

    def test_opaque_images_unchanged(self):
        from PIL import Image

        from backend.app.services.clip_service import _to_rgb

        img = Image.new("RGB", (2, 2), (10, 20, 30))
        assert _to_rgb(img).getpixel((0, 0)) == (10, 20, 30)
