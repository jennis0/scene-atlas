"""Classify pipeline exceptions into user-friendly error messages and error kinds.

Used by the ingestion pipeline to produce three pieces of error information:

1. **reason** — A short, human-readable sentence suitable for showing to the
   user in the import UI.
2. **kind** — How the ingest worker should react (see ADR-018):

   - ``file``      — the file itself is bad; retrying won't help. Fail the item.
   - ``transient`` — a temporary problem; retry the item with backoff.
   - ``system``    — the machine is in a bad state (disk full, model missing);
     pause the queue rather than failing anything.
3. **detail** — The raw exception text, written to the log file for debugging.

Usage::

    from backend.pipeline.error_classifier import classify_ingest_error

    try:
        do_something()
    except Exception as exc:
        error = classify_ingest_error(exc, stage="thumbnails")
        # error == {"reason": "Image is corrupt or ...", "kind": "file",
        #           "stage": "thumbnails", "detail": "..."}
"""

from __future__ import annotations

import errno
import sqlite3

from sqlalchemy.exc import OperationalError as SAOperationalError

from backend.app.services.grid.models import GridModelError

KIND_FILE = "file"
KIND_TRANSIENT = "transient"
KIND_SYSTEM = "system"


class SystemUnavailableError(Exception):
    """Raised when ingest can't proceed because of the machine's state, not the file.

    The message is user-facing (e.g. "Not enough free disk space").
    """


def classify_ingest_error(exc: Exception, stage: str) -> dict[str, str]:
    """Map an exception to a user-friendly error dict.

    Parameters
    ----------
    exc:
        The caught exception.
    stage:
        Pipeline stage where the error occurred.  One of: ``parse``,
        ``copy``, ``thumbnails``, ``colors``, ``grid_detection``,
        ``embedding``, ``db_save``, ``vector_save``.

    Returns
    -------
    dict with keys ``reason`` (user-friendly), ``kind`` (``file`` |
    ``transient`` | ``system``), ``stage``, and ``detail`` (raw exception text).
    """
    reason, kind = _classify(exc, stage)
    return {"reason": reason, "kind": kind, "stage": stage, "detail": str(exc)}


def _is_db_busy(exc: Exception) -> bool:
    if isinstance(exc, SAOperationalError | sqlite3.OperationalError):
        msg = str(exc).lower()
        return "locked" in msg or "busy" in msg
    return False


def _classify(exc: Exception, stage: str) -> tuple[str, str]:
    """Return a (user-friendly reason, kind) pair for the exception."""
    exc_type = type(exc).__name__
    msg = str(exc).lower()

    # --- Explicit system conditions raised by the pipeline itself ---
    if isinstance(exc, SystemUnavailableError):
        return str(exc), KIND_SYSTEM

    if isinstance(exc, GridModelError):
        return "Grid detection models are missing or damaged; reinstall Scene Atlas", KIND_SYSTEM

    if "embedding service unavailable" in msg:
        return "No AI model is available", KIND_SYSTEM

    # --- PIL / image file errors ---
    if exc_type == "UnidentifiedImageError" or "cannot identify image file" in msg:
        return "Image is corrupt or not a supported format", KIND_FILE

    if exc_type == "DecompressionBombError" or "decompression bomb" in msg:
        return "Image is too large to process safely (decompression bomb)", KIND_FILE

    if "truncated" in msg:
        return "Image file is incomplete or truncated", KIND_FILE

    # --- OpenCV read failures ---
    if "could not read image" in msg:
        return "Image could not be read for processing", KIND_FILE

    # --- File system errors ---
    if isinstance(exc, OSError) and getattr(exc, "errno", None) == errno.ENOSPC:
        return "Not enough disk space to process image", KIND_SYSTEM

    if isinstance(exc, FileNotFoundError):
        return "File was not found", KIND_FILE

    if isinstance(exc, PermissionError):
        return "File could not be accessed (permission denied)", KIND_FILE

    # --- Database contention ---
    if _is_db_busy(exc):
        return "The database was busy; will retry", KIND_TRANSIENT

    # --- Memory ---
    if isinstance(exc, MemoryError):
        return "Image is too large to process (out of memory)", KIND_TRANSIENT

    # --- Stage-specific fallbacks ---
    if stage == "embedding":
        return "Failed to generate image embedding", KIND_TRANSIENT

    if stage == "db_save":
        return "Failed to save image to database", KIND_TRANSIENT

    if stage == "vector_save":
        return "Failed to save image embedding to search index", KIND_TRANSIENT

    # --- Generic fallback ---
    # Unknown errors are retried a bounded number of times before failing the
    # item: a deterministic failure costs a few retries, a flaky one recovers.
    return f"Processing failed during {stage}", KIND_TRANSIENT
