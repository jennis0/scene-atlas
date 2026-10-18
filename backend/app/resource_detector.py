"""Compute host-appropriate defaults for concurrency settings on first boot."""

import os

try:
    import psutil as _psutil
except ImportError:  # pragma: no cover
    _psutil = None  # type: ignore[assignment]

_FALLBACK_RAM_GB = 4.0

# Prepare workers are threads in the API's process, so they share the GIL with
# requests. Measured on a 56k-image library (design/resource-management.md):
# imports are no faster above 4 workers, but gallery searches during an import
# go from under ~1.5 s at 4 workers to 4-30 s at 8.
_MAX_PREPARE_WORKERS = 4


def compute_resource_defaults() -> dict[str, int]:
    """Return concurrency defaults tuned to the host CPU count and total RAM.

    max_concurrent_prepare is memory-bounded: each worker holds a decompressed
    battlemap image in memory (can be hundreds of MB). OOM crashes occur when
    this value is too high. It is also capped at _MAX_PREPARE_WORKERS, past
    which workers only slow the API down.

    Uses total RAM (not available) since this runs once at first boot.
    """
    cpu = os.cpu_count() or 2
    ram_gb = _psutil.virtual_memory().total / 1024**3 if _psutil else _FALLBACK_RAM_GB

    # Reserve ~2 GB: CLIP ONNX ~300 MB, LanceDB, Python/uvicorn overhead.
    # ~500 MB per prepare worker for large image decode + thumbnails.
    available_gb = max(0.5, ram_gb - 2.0)
    ram_cap = max(1, int(available_gb / 0.5))

    return {
        "max_job_workers": max(1, min(4, cpu // 2)),
        "max_concurrent_prepare": max(1, min(cpu, _MAX_PREPARE_WORKERS, ram_cap)),
        "max_concurrent_heavy_requests": max(1, min(max(1, cpu // 2), 6)),
    }
