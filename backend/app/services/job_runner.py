"""In-process background job runner with bounded concurrency and status tracking.

Submits and executes background work (retagging, backfills, embedding rebuilds) within
the FastAPI process.  Jobs run in a ``ThreadPoolExecutor`` so heavy
processing (CLIP, thumbnails) doesn't block the async event loop.

Usage from API endpoints::

    from backend.app.services.job_runner import get_job_runner

    runner = get_job_runner()
    runner.submit(rebuild_all_embeddings, name="Rebuild embeddings", force=True)

    # Later — check progress:
    record = runner.get_job(job_id)
    # record.status, record.progress, record.progress_pct, ...
"""

import logging
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from backend.app.config import settings as _settings
from backend.app.services.shutdown import (
    ShutdownRequested,
    request_shutdown,
    shutdown_requested,
)

logger = logging.getLogger(__name__)

_job_runner: "JobRunner | None" = None
_lock = threading.Lock()


@dataclass
class JobRecord:
    """In-memory record of a background job's lifecycle."""

    id: str
    name: str
    status: str = "queued"  # queued → running → completed | failed | interrupted
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
            return datetime.fromtimestamp(t, tz=UTC).isoformat() if t else None

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
        self._shutting_down = threading.Event()
        logger.info("JobRunner started with max_workers=%d", max_workers)

    @property
    def shutting_down(self) -> bool:
        """True once shutdown has begun. Jobs check it through
        ``shutdown.raise_if_shutting_down()`` at batch boundaries."""
        return self._shutting_down.is_set() or shutdown_requested()

    # Public API

    def submit(self, fn: Callable, *args: Any, name: str | None = None, **kwargs: Any) -> str:
        """Run *fn* in the background; returns a job ID for :meth:`get_job`.

        If *fn* accepts a ``progress_fn`` keyword, a progress callback is injected.
        *name* is shown in the status API and defaults to ``fn.__name__``.
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
            except ShutdownRequested:
                record.status = "interrupted"
                record.error = "Interrupted by shutdown"
                logger.info("Background job %s (%s) stopped for shutdown", job_id, job_name)
                return None
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

    def has_active_job(self, name: str) -> bool:
        """Return True if a job with the given name is currently queued or running."""
        with self._lock:
            return any(
                rec.name == name and rec.status in ("queued", "running")
                for rec in self._jobs.values()
            )

    def get_active_job_id(self, name: str) -> str | None:
        """Return the job ID of a queued/running job with the given name, or None."""
        with self._lock:
            for rec in self._jobs.values():
                if rec.name == name and rec.status in ("queued", "running"):
                    return rec.id
            return None

    def shutdown(self, wait: bool = True) -> None:
        """Signal workers to stop, then drain the queue."""
        logger.info("JobRunner shutting down (wait=%s)...", wait)
        self._shutting_down.set()
        request_shutdown()
        self._executor.shutdown(wait=wait, cancel_futures=True)
        logger.info("JobRunner stopped")

    @property
    def status(self) -> dict:
        """Summary for the ``/health`` endpoint."""
        with self._lock:
            self._cleanup_done_futures()
            active = sum(1 for f in self._futures.values() if f.running())
            pending = sum(1 for f in self._futures.values() if not f.done() and not f.running())
        return {
            "max_workers": self._max_workers,
            "active_jobs": active,
            "pending_jobs": pending,
        }

    # Internal

    def _cleanup_done_futures(self) -> None:
        """Remove references to completed futures (prevent memory leak)."""
        done_ids = [jid for jid, f in self._futures.items() if f.done()]
        for jid in done_ids:
            del self._futures[jid]

    def _cleanup_old_jobs(self) -> None:
        """Remove job records that finished more than job_retention_seconds ago."""
        now = time.time()
        expired = [
            jid
            for jid, rec in self._jobs.items()
            if rec.finished_at and (now - rec.finished_at) > _settings.job_retention_seconds
        ]
        for jid in expired:
            del self._jobs[jid]


def get_job_runner() -> JobRunner:
    """Return the global JobRunner singleton (created on first call).

    max_workers is read from DB-backed AppSettings so it can be changed
    at runtime (takes effect on next restart, not while running).
    """
    global _job_runner
    if _job_runner is not None:
        return _job_runner
    with _lock:
        if _job_runner is None:
            max_workers = 2  # safe fallback
            try:
                from ..config import settings
                from ..models.database import get_engine, get_session_local
                from .app_settings import get_settings as get_app_settings

                engine = get_engine(settings.database_url)
                SessionLocal = get_session_local(engine)
                db = SessionLocal()
                try:
                    max_workers = get_app_settings(db).max_job_workers
                finally:
                    db.close()
            except Exception:
                # DB may not be ready on very first boot — use default
                logger.debug("Could not read max_job_workers; using default", exc_info=True)
            _job_runner = JobRunner(max_workers=max_workers)
    return _job_runner


def shutdown_job_runner() -> None:
    """Shut down the global JobRunner if it exists."""
    global _job_runner
    if _job_runner is not None:
        _job_runner.shutdown(wait=True)
        _job_runner = None
