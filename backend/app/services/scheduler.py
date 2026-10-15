"""Lightweight periodic task scheduler.

Runs maintenance tasks (database backup, ingest maintenance, orphan sweep,
vector reconciliation) at fixed intervals inside the FastAPI process using
``asyncio`` tasks started during the application lifespan.

Each task's last successful run is recorded on disk, so a task that is overdue
when the app starts runs shortly after startup instead of a full interval
later. Without this, desktop sessions shorter than a task's interval would never
run it at all.

Usage::

    scheduler = Scheduler(state_dir)
    scheduler.register(fn, hours=6)
    await scheduler.start()   # in lifespan startup
    await scheduler.stop()    # in lifespan shutdown
"""

import asyncio
import logging
import time
from collections.abc import Callable
from pathlib import Path

logger = logging.getLogger(__name__)

# Delay before the first overdue run, so startup isn't competing with maintenance.
STARTUP_GRACE_SECONDS = 60.0


class Scheduler:
    """Run periodic maintenance functions on a fixed interval.

    Each registered function runs in the default executor (thread pool)
    so it won't block the async event loop.
    """

    def __init__(
        self, state_dir: Path | None = None, startup_grace: float = STARTUP_GRACE_SECONDS
    ) -> None:
        self._registered: list[tuple[Callable, float, str]] = []
        self._tasks: list[asyncio.Task] = []
        self._state_dir = state_dir
        self._startup_grace = startup_grace

    def register(self, fn: Callable, *, hours: float, name: str | None = None) -> None:
        """Register a function to run every ``hours`` hours.

        Must be called *before* :meth:`start`.  The function is called
        with no arguments and may be sync (it runs in an executor).
        """
        self._registered.append((fn, hours, name or fn.__name__))

    async def start(self) -> None:
        """Start all registered periodic tasks."""
        if self._state_dir is not None:
            self._state_dir.mkdir(parents=True, exist_ok=True)
        for fn, hours, label in self._registered:
            delay = self.first_delay(label, hours * 3600)
            self._tasks.append(asyncio.create_task(self._loop(fn, hours * 3600, label, delay)))
            logger.info("Scheduled %s every %.1fh (first run in %.0fs)", label, hours, delay)

    async def stop(self) -> None:
        """Cancel all running periodic tasks."""
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks = []
        logger.info("Scheduler stopped")

    # --- last-run bookkeeping ---------------------------------------------------

    def _marker(self, label: str) -> Path | None:
        return self._state_dir / f"{label}.last_run" if self._state_dir else None

    def last_run(self, label: str) -> float | None:
        marker = self._marker(label)
        try:
            return float(marker.read_text()) if marker else None
        except (OSError, ValueError):
            return None

    def _record_run(self, label: str) -> None:
        marker = self._marker(label)
        if marker is not None:
            try:
                marker.write_text(str(time.time()))
            except OSError:
                logger.warning("Could not record last run of %s", label, exc_info=True)

    def first_delay(self, label: str, interval: float) -> float:
        """Seconds until a task's first run: overdue tasks run after the startup grace."""
        last = self.last_run(label)
        if last is None:
            return self._startup_grace
        remaining = interval - (time.time() - last)
        return max(self._startup_grace, remaining)

    # --- loop ------------------------------------------------------------------

    async def _loop(self, fn: Callable, interval: float, label: str, delay: float) -> None:
        """Wait, run, repeat."""
        while True:
            await asyncio.sleep(delay)
            delay = interval
            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, fn)
                self._record_run(label)
                logger.info("Scheduled task %s completed", label)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Scheduled task %s failed", label)
