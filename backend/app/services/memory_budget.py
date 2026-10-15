"""Memory-aware admission for image processing (design/ingest-redesign.md, Phase 0 follow-up).

The prepare pool bounds how many images are processed at once, but not how big
they are: a 760 Mpx map needs gigabytes while a typical map needs tens of
megabytes. Each prepare step reserves its estimated peak from a shared budget
before decoding and waits while the budget is exhausted.

An item larger than the whole budget is admitted on its own (when nothing else
holds a reservation) rather than deadlocking.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterator
from contextlib import contextmanager

logger = logging.getLogger(__name__)

_GIB = 1024**3


def default_capacity_bytes() -> int:
    """Half of RAM beyond a 2 GiB reserve, at least 1 GiB."""
    try:
        import psutil

        total = psutil.virtual_memory().total
    except Exception:  # psutil missing or unsupported platform
        total = 4 * _GIB
    return max(_GIB, int((total - 2 * _GIB) * 0.5))


class MemoryBudget:
    def __init__(self, capacity_bytes: int):
        if capacity_bytes <= 0:
            raise ValueError("capacity must be positive")
        self._capacity = capacity_bytes
        self._used = 0
        self._cond = threading.Condition()

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def in_use(self) -> int:
        with self._cond:
            return self._used

    @contextmanager
    def reserve(self, nbytes: int) -> Iterator[None]:
        """Hold ``nbytes`` of the budget for the duration of the block."""
        amount = max(0, min(int(nbytes), self._capacity))
        with self._cond:
            while self._used and self._used + amount > self._capacity:
                self._cond.wait()
            self._used += amount
        try:
            yield
        finally:
            with self._cond:
                self._used -= amount
                self._cond.notify_all()


_budget: MemoryBudget | None = None
_budget_lock = threading.Lock()


def get_memory_budget() -> MemoryBudget:
    global _budget
    with _budget_lock:
        if _budget is None:
            from ..config import settings

            capacity = (
                settings.ingest_memory_budget_mb * 1024 * 1024
                if settings.ingest_memory_budget_mb
                else default_capacity_bytes()
            )
            _budget = MemoryBudget(capacity)
            logger.info("Ingest memory budget: %.1f GiB", capacity / _GIB)
        return _budget
