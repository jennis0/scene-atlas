"""How long this computer takes to import one file, measured (design/import-progress.md §4).

A rolling average over the last ``window`` files the worker settled in this session: each
batch adds its wall time and the files it finished, and the oldest batches drop off once the
rest still cover the window. No model of image size or hardware: a slow disk, a big map or a
busy CPU all show up in the measurement. Kept in memory, so a restart starts afresh.
"""

from __future__ import annotations

import threading
from collections import deque

DEFAULT_WINDOW = 100


class ProcessingRate:
    def __init__(self, window: int = DEFAULT_WINDOW):
        self._window = window
        self._batches: deque[tuple[int, float]] = deque()
        self._files = 0
        self._seconds = 0.0
        self._lock = threading.Lock()

    def record(self, files: int, seconds: float) -> None:
        """A batch settled ``files`` files in ``seconds``. Empty batches are ignored."""
        if files <= 0:
            return
        with self._lock:
            self._batches.append((files, seconds))
            self._files += files
            self._seconds += seconds
            while self._batches and self._files - self._batches[0][0] >= self._window:
                old_files, old_seconds = self._batches.popleft()
                self._files -= old_files
                self._seconds -= old_seconds

    def seconds_per_item(self) -> float | None:
        """Average seconds per file over the window, or None before the first batch."""
        with self._lock:
            return self._seconds / self._files if self._files else None
