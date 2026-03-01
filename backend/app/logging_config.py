"""Centralised logging configuration for Scene Atlas.

Configures the root logger with both console and rotating file output.
Call ``setup_logging()`` once from each entry point (FastAPI startup,
PyInstaller sidecar, CLI scripts) before any other module logs.
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOG_FORMAT = "%(asctime)s %(levelname)-8s [%(name)s] %(message)s"
_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
_BACKUP_COUNT = 5
_CONFIGURED = False


def setup_logging(data_dir: Path, *, debug: bool = False) -> None:
    """Configure root logger with console + rotating file handlers.

    Parameters
    ----------
    data_dir:
        Base data directory.  Logs are written to ``{data_dir}/logs/scene-atlas.log``.
    debug:
        When True, both handlers use DEBUG level; otherwise INFO.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return
    _CONFIGURED = True

    level = logging.DEBUG if debug else logging.INFO
    log_dir = data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "scene-atlas.log"

    root = logging.getLogger()
    root.setLevel(level)
    formatter = logging.Formatter(_LOG_FORMAT)

    # Console handler (stdout)
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(formatter)
    root.addHandler(console)

    # Rotating file handler
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)
