"""Lightweight periodic task scheduler.

Runs maintenance tasks (database backup, staging cleanup) at fixed intervals
inside the FastAPI process using ``asyncio`` tasks started during the
application lifespan.

Usage::

    scheduler = Scheduler()
    await scheduler.start()   # in lifespan startup
    await scheduler.stop()    # in lifespan shutdown
"""

import asyncio
import logging
from typing import Callable

logger = logging.getLogger(__name__)


class Scheduler:
    """Run periodic maintenance functions on a fixed interval.

    Each registered function runs in the default executor (thread pool)
    so it won't block the async event loop.
    """

    def __init__(self) -> None:
        self._tasks: list[asyncio.Task] = []

    def register(self, fn: Callable, *, hours: float, name: str | None = None) -> None:
        """Register a function to run every ``hours`` hours.

        Must be called *before* :meth:`start`.  The function is called
        with no arguments and may be sync (it runs in an executor).
        """
        label = name or fn.__name__
        self._tasks.append((fn, hours, label))  # type: ignore[arg-type]

    async def start(self) -> None:
        """Start all registered periodic tasks."""
        running = []
        for fn, hours, label in self._tasks:  # type: ignore[misc]
            task = asyncio.create_task(self._loop(fn, hours, label))
            running.append(task)
            logger.info("Scheduled %s every %.1fh", label, hours)
        self._tasks = running  # type: ignore[assignment]

    async def stop(self) -> None:
        """Cancel all running periodic tasks."""
        for task in self._tasks:
            if isinstance(task, asyncio.Task):
                task.cancel()
        for task in self._tasks:
            if isinstance(task, asyncio.Task):
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._tasks = []
        logger.info("Scheduler stopped")

    @staticmethod
    async def _loop(fn: Callable, hours: float, label: str) -> None:
        """Sleep-then-run loop for one periodic function."""
        interval = hours * 3600
        while True:
            await asyncio.sleep(interval)
            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, fn)
                logger.info("Scheduled task %s completed", label)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Scheduled task %s failed", label)
