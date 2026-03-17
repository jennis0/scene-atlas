"""Classify pipeline exceptions into user-friendly error messages.

Used by the ingestion pipeline to produce two levels of error information:

1. **reason** — A short, human-readable sentence suitable for showing to the
   user in the import UI (Phase 2).
2. **detail** — The raw exception text, written to the log file for debugging.

Usage::

    from backend.pipeline.error_classifier import classify_ingest_error

    try:
        do_something()
    except Exception as exc:
        error = classify_ingest_error(exc, stage="thumbnails")
        # error == {"reason": "Image is corrupt or ...", "stage": "thumbnails", "detail": "..."}
"""

from __future__ import annotations

import errno


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
    dict with keys ``reason`` (user-friendly), ``stage``, and ``detail``
    (raw exception text).
    """
    detail = str(exc)
    reason = _classify(exc, stage)
    return {"reason": reason, "stage": stage, "detail": detail}


def _classify(exc: Exception, stage: str) -> str:
    """Return a user-friendly reason string for the exception."""
    exc_type = type(exc).__name__
    msg = str(exc).lower()

    # --- PIL / image file errors ---
    if exc_type == "UnidentifiedImageError" or "cannot identify image file" in msg:
        return "Image is corrupt or not a supported format"

    if exc_type == "DecompressionBombError" or "decompression bomb" in msg:
        return "Image is too large to process safely (decompression bomb)"

    # --- OpenCV read failures ---
    if "could not read image" in msg:
        return "Image could not be read for processing"

    # --- File system errors ---
    if isinstance(exc, FileNotFoundError):
        return "File was not found"

    if isinstance(exc, PermissionError):
        return "File could not be accessed (permission denied)"

    if isinstance(exc, OSError) and getattr(exc, "errno", None) == errno.ENOSPC:
        return "Not enough disk space to process image"

    # --- Memory ---
    if isinstance(exc, MemoryError):
        return "Image is too large to process (out of memory)"

    # --- Stage-specific fallbacks ---
    if stage == "embedding":
        return "Failed to generate image embedding"

    if stage == "db_save":
        return "Failed to save image to database"

    if stage == "vector_save":
        return "Failed to save image embedding to search index"

    # --- Generic fallback ---
    return f"Processing failed during {stage}"
