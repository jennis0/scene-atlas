"""Cross-platform process utility helpers."""

import os


def get_rss_mb() -> float | None:
    """Return current process RSS in MiB, or None if unavailable."""
    try:
        import psutil

        return psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)
    except OSError:
        return None
