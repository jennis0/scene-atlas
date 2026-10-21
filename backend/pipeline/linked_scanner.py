"""When the linked folder is scanned (design/library-setup.md §4.3): one scan at a time, at
startup, on the ``linked_rescan_minutes`` timer, when the desktop window regains focus,
and on demand. What a scan does is ``linked_scan``.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Literal

from backend.app.services.app_settings import get_settings as get_app_settings
from backend.app.services.originals import forget_availability
from backend.app.services.shutdown import ShutdownRequested

from .ingest_queue import _session
from .linked_scan import ScanResult, scan_linked_folder

logger = logging.getLogger(__name__)

# A focus rescan is ignored this soon after the last scan started.
FOCUS_MIN_INTERVAL = 60.0
# How often the rescan timer wakes to read linked_rescan_minutes.
TIMER_WAKE_SECONDS = 60.0

ScanReason = Literal["startup", "timer", "focus", "manual"]


class LinkedScanner:
    """Runs scans one at a time, on a background thread or the caller's."""

    def __init__(self, scan=scan_linked_folder):
        self._scan = scan
        self._lock = threading.Lock()
        self._running = False
        self._last_started: float | None = None
        self._last_finished: float | None = None

    @property
    def running(self) -> bool:
        return self._running

    def _begin(self) -> bool:
        with self._lock:
            if self._running:
                return False
            self._running = True
            self._last_started = time.monotonic()
            return True

    def _run(self) -> ScanResult | None:
        from .ingest_worker import get_ingest_worker

        try:
            result = self._scan()
        except ShutdownRequested:
            return None
        except Exception:
            logger.exception("Linked folder scan failed")
            return None
        finally:
            with self._lock:
                self._running = False
                self._last_finished = time.monotonic()
            forget_availability()
        worker = get_ingest_worker()
        worker.bump()
        if result.job_id:
            worker.wake()
        return result

    def scan(self) -> ScanResult | None:
        """Scan now, on this thread. None if a scan is already running (or it failed)."""
        return self._run() if self._begin() else None

    def start(self, reason: ScanReason) -> bool:
        """Start a scan on a background thread unless one is running. A ``focus`` scan
        is also skipped within a minute of the last one. Returns whether it started."""
        if reason == "focus" and self.started_within(FOCUS_MIN_INTERVAL):
            return False
        if not self._begin():
            return False
        logger.debug("Linked scan started (%s)", reason)
        threading.Thread(target=self._run, name="linked-scan", daemon=True).start()
        return True

    def started_within(self, seconds: float) -> bool:
        started = self._last_started
        return started is not None and time.monotonic() - started < seconds

    def due(self, minutes: int) -> bool:
        """Whether the timer should scan: rescans are on and the last one finished at
        least ``minutes`` ago."""
        if minutes <= 0 or self._running:
            return False
        finished = self._last_finished
        return finished is None or time.monotonic() - finished >= minutes * 60


_scanner: LinkedScanner | None = None


def get_linked_scanner() -> LinkedScanner:
    global _scanner
    if _scanner is None:
        _scanner = LinkedScanner()
    return _scanner


def _rescan_minutes() -> int:
    with _session() as db:
        return get_app_settings(db).linked_rescan_minutes


async def rescan_timer(wake_seconds: float = TIMER_WAKE_SECONDS) -> None:
    """Scan every ``linked_rescan_minutes`` (0: only at startup). The setting is read at
    each wake, so a change applies without a restart; any scan restarts the interval."""
    scanner = get_linked_scanner()
    while True:
        await asyncio.sleep(wake_seconds)
        try:
            minutes = await asyncio.to_thread(_rescan_minutes)
        except Exception:
            logger.warning("Couldn't read linked_rescan_minutes", exc_info=True)
            continue
        if scanner.due(minutes):
            scanner.start("timer")
