"""Centralised logging configuration for Scene Atlas.

Configures the root logger with both console and rotating file output.
Call ``setup_logging()`` once from each entry point (FastAPI startup,
PyInstaller sidecar, CLI scripts) before any other module logs.
"""

import logging
import sys
import warnings
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

    # Route Python warnings through the logging system so they appear in the
    # log file rather than going to stderr and being silently lost.
    logging.captureWarnings(True)

    # PIL DecompressionBombWarning: large battlemaps (100M+ px) trigger this.
    # Convert to an error so the pipeline catches it, classifies it, and logs
    # it with full context (which file, which stage) rather than a bare stderr line.
    try:
        from PIL import Image

        warnings.filterwarnings("error", category=Image.DecompressionBombWarning)
    except ImportError:
        pass  # PIL not installed yet (e.g. during fresh env setup)

    # sklearn ConvergenceWarning: expected when an image has fewer distinct
    # colours than the requested k-means clusters.  Demote to DEBUG so it
    # doesn't clutter INFO logs on normal uploads.
    warnings.filterwarnings(
        "ignore",
        message="Number of distinct clusters.*found smaller than n_clusters",
        category=UserWarning,
        module="sklearn",
    )
