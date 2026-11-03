"""Cross-platform process utility helpers."""

import os


def get_rss_mb() -> float | None:
    """Return current process RSS in MiB, or None if unavailable."""
    try:
        import psutil

        return psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)
    except OSError:
        return None


def release_freed_memory() -> bool:
    """Collect garbage, then hand the C heap's free pages back to the OS (``malloc_trim``,
    glibc only). Returns whether it trimmed.

    After a memory-heavy step (an import's grouping phase) glibc keeps freed memory in its
    arenas: ~310 MB of a 10k-image grouping before its fixes, ~90 MB after
    (design/resource-management.md). Elsewhere (macOS, Windows, musl) only ``gc`` runs.
    """
    import gc
    import sys

    gc.collect()
    if not sys.platform.startswith("linux"):
        return False
    try:
        import ctypes

        libc = ctypes.CDLL("libc.so.6")
        trim = libc.malloc_trim
    except (OSError, AttributeError):
        return False
    trim.argtypes = [ctypes.c_size_t]
    trim.restype = ctypes.c_int
    trim(0)
    return True
