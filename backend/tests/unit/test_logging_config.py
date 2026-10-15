"""Tests for backend.app.logging_config."""

import logging
from logging.handlers import RotatingFileHandler

import pytest

import backend.app.logging_config as logging_config_mod
from backend.app.logging_config import setup_logging


@pytest.fixture(autouse=True)
def _clean_root_logger():
    """Reset the module flag and remove our handlers before/after each test.

    Pytest adds its own ``LogCaptureHandler`` to the root logger.  We only
    remove handlers that *we* added (StreamHandler to stdout and
    RotatingFileHandler) and leave pytest's handlers alone.
    """
    import sys

    # Reset the module-level guard so setup_logging can run again
    logging_config_mod._CONFIGURED = False

    root = logging.getLogger()
    original_level = root.level

    # Remove any pre-existing setup_logging handlers (e.g. added when main.py
    # was imported by integration tests earlier in the test session).
    for h in root.handlers[:]:
        if isinstance(h, RotatingFileHandler):
            h.close()
            root.removeHandler(h)
        elif type(h) is logging.StreamHandler and getattr(h, "stream", None) is sys.stdout:
            root.removeHandler(h)

    original_handlers = root.handlers[:]

    yield

    # Teardown: remove only the handlers we added, close file handlers
    for h in root.handlers[:]:
        if isinstance(h, RotatingFileHandler):
            h.close()
            root.removeHandler(h)
        elif isinstance(h, logging.StreamHandler) and h not in original_handlers:
            root.removeHandler(h)

    root.level = original_level
    logging_config_mod._CONFIGURED = False


def _our_handlers() -> list[logging.Handler]:
    """Return only the handlers added by setup_logging (not pytest's).

    Our StreamHandler writes to sys.stdout; pytest's capture handlers
    wrap tempfiles, so we distinguish by checking the stream target.
    """
    import sys

    root = logging.getLogger()
    result = []
    for h in root.handlers:
        if isinstance(h, RotatingFileHandler):
            result.append(h)
        elif type(h) is logging.StreamHandler and getattr(h, "stream", None) is sys.stdout:
            result.append(h)
    return result


class TestSetupLogging:
    """setup_logging configures root logger with console + file handlers."""

    def test_creates_log_directory(self, tmp_path):
        log_dir = tmp_path / "logs"
        assert not log_dir.exists()
        setup_logging(tmp_path)
        assert log_dir.exists()

    def test_creates_log_file(self, tmp_path):
        setup_logging(tmp_path)
        log_file = tmp_path / "logs" / "scene-atlas.log"
        # Log something to flush to file
        logger = logging.getLogger("test.logging_config")
        logger.info("test message")
        for h in _our_handlers():
            h.flush()
        assert log_file.exists()

    def test_adds_our_handlers(self, tmp_path):
        setup_logging(tmp_path)
        assert len(_our_handlers()) == 2

    def test_console_handler_present(self, tmp_path):
        setup_logging(tmp_path)
        stream_handlers = [h for h in _our_handlers() if type(h) is logging.StreamHandler]
        assert len(stream_handlers) == 1

    def test_file_handler_present(self, tmp_path):
        setup_logging(tmp_path)
        file_handlers = [h for h in _our_handlers() if isinstance(h, RotatingFileHandler)]
        assert len(file_handlers) == 1

    def test_info_level_default(self, tmp_path):
        setup_logging(tmp_path)
        root = logging.getLogger()
        assert root.level == logging.INFO

    def test_debug_level_when_debug(self, tmp_path):
        setup_logging(tmp_path, debug=True)
        root = logging.getLogger()
        assert root.level == logging.DEBUG

    def test_raises_pillow_pixel_limit(self, tmp_path, monkeypatch):
        """Large battlemaps (Pillow's default rejects >89.5 Mpx) must be decodable."""
        from PIL import Image

        from backend.app.config import settings

        monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", Image.MAX_IMAGE_PIXELS)
        setup_logging(tmp_path)
        assert Image.MAX_IMAGE_PIXELS == settings.max_image_pixels
        assert settings.max_image_pixels >= 760_000_000

    def test_idempotent(self, tmp_path):
        """Calling setup_logging twice does not add duplicate handlers."""
        setup_logging(tmp_path)
        setup_logging(tmp_path)
        assert len(_our_handlers()) == 2

    def test_message_written_to_file(self, tmp_path):
        setup_logging(tmp_path)
        logger = logging.getLogger("test.file_output")
        logger.info("hello from test")

        for h in _our_handlers():
            h.flush()

        log_file = tmp_path / "logs" / "scene-atlas.log"
        content = log_file.read_text()
        assert "hello from test" in content
