"""In-process background job runner with bounded concurrency and status tracking.

Submits and executes background work (imports, retagging, backfills) within
the FastAPI process.  Jobs run in a ``ThreadPoolExecutor`` so heavy
processing (CLIP, thumbnails) doesn't block the async event loop.

Usage from API endpoints::

    from backend.app.services.job_runner import get_job_runner

    runner = get_job_runner()
    runner.submit(process_import_job, job_id=..., name="Import: MyMaps")

    # Later — check progress:
    record = runner.get_job(job_id)
    # record.status, record.progress, record.progress_pct, ...
"""

import logging
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

logger = logging.getLogger(__name__)

_job_runner: "JobRunner | None" = None
_lock = threading.Lock()

# Completed/failed jobs are kept in memory for this long before being cleaned up.
_JOB_RETENTION_SECS = 3600  # 1 hour


@dataclass
class JobRecord:
    """In-memory record of a background job's lifecycle."""

    id: str
    name: str
    status: str = "queued"  # queued → running → completed | failed
    submitted_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    progress: str | None = None
    progress_current: int | None = None
    progress_total: int | None = None
    result: Any = None
    error: str | None = None

    @property
    def progress_pct(self) -> int | None:
        """Integer percentage 0–100, or None if no progress info."""
        if self.progress_current is not None and self.progress_total and self.progress_total > 0:
            return min(100, int(100 * self.progress_current / self.progress_total))
        return None

    def to_dict(self) -> dict:
        """Serialise for API responses."""

        def _ts(t: float | None) -> str | None:
            return datetime.fromtimestamp(t, tz=timezone.utc).isoformat() if t else None

        return {
            "id": self.id,
            "name": self.name,
            "status": self.status,
            "submitted_at": _ts(self.submitted_at),
            "started_at": _ts(self.started_at),
            "finished_at": _ts(self.finished_at),
            "progress": self.progress,
            "progress_pct": self.progress_pct,
            "result": self.result,
            "error": self.error,
        }


class JobRunner:
    """Background job runner backed by a thread pool.

    Parameters
    ----------
    max_workers:
        Maximum concurrent jobs.  Default 2 allows one import + one
        maintenance/backfill job to run simultaneously.  The CLIP model
        is thread-safe for inference so sharing across workers is fine.
    """

    def __init__(self, max_workers: int = 2) -> None:
        self._max_workers = max_workers
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="job",
        )
        self._futures: dict[str, Future] = {}
        self._jobs: dict[str, JobRecord] = {}
        self._lock = threading.Lock()
        logger.info("JobRunner started with max_workers=%d", max_workers)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def submit(
        self, fn: Callable, *args: Any, name: str | None = None, **kwargs: Any
    ) -> str:
        """Submit a callable for background execution.

        Parameters
        ----------
        fn:
            The function to execute.  If ``fn`` accepts a ``progress_fn``
            keyword argument, a progress callback is injected automatically.
        name:
            Human-readable job name (shown in status API).  Defaults to
            ``fn.__name__``.
        *args, **kwargs:
            Forwarded to ``fn``.

        Returns
        -------
        str
            A job ID that can be used with :meth:`get_job` to poll status.
        """
        job_id = uuid.uuid4().hex[:16]
        job_name = name or fn.__name__

        record = JobRecord(id=job_id, name=job_name)

        # Build a progress callback bound to this record
        def _progress(current: int, total: int, message: str | None = None) -> None:
            record.progress_current = current
            record.progress_total = total
            if message:
                record.progress = message

        # Inject progress_fn if the callable accepts it
        import inspect

        sig = inspect.signature(fn)
        if "progress_fn" in sig.parameters:
            kwargs["progress_fn"] = _progress

        def _wrapped() -> Any:
            record.status = "running"
            record.started_at = time.time()
            try:
                result = fn(*args, **kwargs)
                record.status = "completed"
                record.result = result
                return result
            except Exception as exc:
                record.status = "failed"
                record.error = str(exc)
                logger.exception("Background job %s (%s) failed", job_id, job_name)
                raise
            finally:
                record.finished_at = time.time()

        future = self._executor.submit(_wrapped)
        with self._lock:
            self._futures[job_id] = future
            self._jobs[job_id] = record
            self._cleanup_done_futures()
        logger.info("Submitted job %s: %s", job_id, job_name)
        return job_id

    def get_job(self, job_id: str) -> JobRecord | None:
        """Return the status record for a job, or None if expired/unknown."""
        with self._lock:
            self._cleanup_old_jobs()
            return self._jobs.get(job_id)

    def list_jobs(self) -> list[JobRecord]:
        """Return all tracked jobs (running + recently completed)."""
        with self._lock:
            self._cleanup_old_jobs()
            return list(self._jobs.values())

    def run_sync(self, fn: Callable, *args: Any, timeout: float = 120, **kwargs: Any) -> Any:
        """Run a function in the thread pool and block until complete.

        Used for ``analyse_upload`` which the API endpoint must await.
        """
        future = self._executor.submit(fn, *args, **kwargs)
        return future.result(timeout=timeout)

    def shutdown(self, wait: bool = True) -> None:
        """Drain the queue and shut down worker threads."""
        logger.info("JobRunner shutting down (wait=%s)...", wait)
        self._executor.shutdown(wait=wait)
        logger.info("JobRunner stopped")

    @property
    def status(self) -> dict:
        """Summary for the ``/health`` endpoint."""
        with self._lock:
            self._cleanup_done_futures()
            active = sum(1 for f in self._futures.values() if f.running())
            pending = sum(
                1 for f in self._futures.values() if not f.done() and not f.running()
            )
        return {
            "max_workers": self._max_workers,
            "active_jobs": active,
            "pending_jobs": pending,
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _cleanup_done_futures(self) -> None:
        """Remove references to completed futures (prevent memory leak)."""
        done_ids = [jid for jid, f in self._futures.items() if f.done()]
        for jid in done_ids:
            del self._futures[jid]

    def _cleanup_old_jobs(self) -> None:
        """Remove job records that finished more than _JOB_RETENTION_SECS ago."""
        now = time.time()
        expired = [
            jid
            for jid, rec in self._jobs.items()
            if rec.finished_at and (now - rec.finished_at) > _JOB_RETENTION_SECS
        ]
        for jid in expired:
            del self._jobs[jid]


def get_job_runner() -> JobRunner:
    """Return the global JobRunner singleton (created on first call)."""
    global _job_runner
    if _job_runner is not None:
        return _job_runner
    with _lock:
        if _job_runner is None:
            from ..config import settings

            _job_runner = JobRunner(max_workers=settings.max_job_workers)
    return _job_runner


def shutdown_job_runner() -> None:
    """Shut down the global JobRunner if it exists."""
    global _job_runner
    if _job_runner is not None:
        _job_runner.shutdown(wait=True)
        _job_runner = None
