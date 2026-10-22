"""The ingest worker: claims and processes import items (ADR-018, design §5).

One loop thread per process. It sleeps until woken (bytes received, seal,
resume, retry) or a periodic timeout, claims a batch round-robin across jobs,
processes it, and repeats. Per-image parallelism comes from the shared prepare
pool, not from this thread.

System pause: when the machine is in a bad state (AI model missing, library
drive unavailable, disk nearly full), the worker stops claiming and re-probes
periodically instead of failing items. The reason is exposed via ``status()``.

Tests drive the worker synchronously with ``drain()``; no thread is needed.
"""

from __future__ import annotations

import logging
import shutil
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from backend.app.config import settings
from backend.app.services import get_image_store, get_thumbnail_store
from backend.app.services.prepare_pool import get_prepare_pool

from .ingest_process import BatchOutcome, clear_incoming, process_batch, settled_count
from .ingest_queue import claim_next_batch, recover_interrupted
from .ingest_rate import ProcessingRate
from .pipeline_config import PipelineConfig, load_pipeline_config
from .refine_groups import schedule_refinements

logger = logging.getLogger(__name__)

# Below this much free space on any ingest volume, the queue pauses.
MIN_FREE_BYTES = 512 * 1024 * 1024
# While idle, jobs due for grouping refinement are looked for at most this often. Catches
# jobs finished without a batch (cancel, skip, finish without missing files) and ones
# deferred while the model was busy (design/ingestion.md §5.8).
REFINEMENT_SWEEP_SECONDS = 60.0

Probe = Callable[[], str | None]


def default_probe() -> str | None:
    """Return a user-facing reason ingest can't run right now, or None if it can."""
    from backend.app.services.clip_service import get_clip_unavailable_reason

    reason = get_clip_unavailable_reason()
    if reason:
        return reason
    library = get_image_store().base_dir
    if not library.exists():
        return "The image library folder is unavailable"
    volumes = (
        (library, "image library"),
        (get_thumbnail_store().base_dir, "app data"),
        (settings.staging_dir, "app data"),
    )
    for path, label in volumes:
        try:
            free = shutil.disk_usage(path).free
        except OSError:
            return f"The {label} folder is unavailable"
        if free < MIN_FREE_BYTES:
            return f"Not enough free disk space on the {label} drive"
    return None


@dataclass(frozen=True)
class WorkerStatus:
    running: bool
    system_paused: bool
    system_reason: str | None
    current_job_id: str | None
    version: int
    # Rolling average time to import one file this session (None until measured)
    seconds_per_item: float | None = None


class IngestWorker:
    def __init__(
        self,
        *,
        config_loader: Callable[[], PipelineConfig] = load_pipeline_config,
        probe: Probe = default_probe,
        pool_getter=get_prepare_pool,
        idle_wait: float = 30.0,
        probe_interval: float = 30.0,
    ):
        self._config_loader = config_loader
        self._probe = probe
        self._pool_getter = pool_getter
        self._idle_wait = idle_wait
        self._probe_interval = probe_interval

        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Condition()
        self._cursor: str | None = None
        self._current_job_id: str | None = None
        self._system_reason: str | None = None
        self._holds: dict[str, str] = {}  # external pauses, e.g. a model switch
        self._busy = False
        self._last_probe = 0.0
        self._last_refinement_sweep: float | None = None
        self._version = 0
        self._rate = ProcessingRate()

    # --- lifecycle -----------------------------------------------------------

    def recover(self) -> dict[str, int]:
        """Startup recovery: clear temp files, re-queue items left processing."""
        clear_incoming()
        result = recover_interrupted()
        self.bump()
        return result

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="ingest-worker", daemon=True)
        self._thread.start()

    def stop(self, timeout: float | None = None) -> None:
        """Stop after the batch in progress (if any) finishes."""
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None

    def wake(self) -> None:
        self._wake.set()

    def bump(self) -> None:
        """Mark progress state as changed (drives cheap ETag polling)."""
        with self._lock:
            self._version += 1

    def status(self) -> WorkerStatus:
        with self._lock:
            reason = next(iter(self._holds.values()), None) or self._system_reason
            return WorkerStatus(
                running=self._thread is not None,
                system_paused=reason is not None,
                system_reason=reason,
                current_job_id=self._current_job_id,
                version=self._version,
                seconds_per_item=self._rate.seconds_per_item(),
            )

    def is_held(self) -> bool:
        """True while something holds the queue (``held``), e.g. a model switch."""
        with self._lock:
            return bool(self._holds)

    @contextmanager
    def held(self, reason: str, timeout: float | None = None) -> Iterator[None]:
        """Pause the queue for the duration of the block, e.g. while the AI model changes.

        Waits (up to ``timeout``) for a batch already in progress to finish, so no
        batch spans the held operation. Shown to users as a system pause.
        """
        key = uuid.uuid4().hex
        with self._lock:
            self._holds[key] = reason
            self._version += 1
            self._lock.wait_for(lambda: not self._busy, timeout)
        logger.info("Ingest held: %s", reason)
        try:
            yield
        finally:
            with self._lock:
                self._holds.pop(key, None)
                self._version += 1
            self.wake()

    # --- system pause ----------------------------------------------------------

    def probe_now(self) -> str | None:
        """Re-check system conditions immediately ("Retry now")."""
        reason = self._probe()
        self._last_probe = time.monotonic()
        self._set_system_reason(reason)
        if reason is None:
            self.wake()
        return reason

    def _set_system_reason(self, reason: str | None) -> None:
        with self._lock:
            changed = reason != self._system_reason
            self._system_reason = reason
            if changed:
                self._version += 1
        if changed and reason:
            logger.warning("Ingest paused: %s", reason)
        elif changed:
            logger.info("Ingest resumed")

    # --- work ------------------------------------------------------------------

    def run_once(self) -> bool:
        """Process at most one batch. Returns True if any work was done."""
        with self._lock:
            if self._holds:
                return False
            self._busy = True
        try:
            return self._run_once()
        finally:
            with self._lock:
                self._busy = False
                self._lock.notify_all()

    def _run_once(self) -> bool:
        if self._system_reason is not None:
            if time.monotonic() - self._last_probe < self._probe_interval:
                return False
            if self.probe_now() is not None:
                return False
        else:
            reason = self._probe()
            if reason is not None:
                self._last_probe = time.monotonic()
                self._set_system_reason(reason)
                return False

        cfg = self._config_loader()
        job_id, items = claim_next_batch(self._cursor, max(1, cfg.ingestion_batch_size))
        if not items:
            self._sweep_refinements()
            return False

        self._cursor = job_id
        with self._lock:
            self._current_job_id = job_id
        started = time.monotonic()
        try:
            outcome: BatchOutcome = process_batch(items, cfg, self._pool_getter())
            self._rate.record(settled_count(items, outcome), time.monotonic() - started)
        finally:
            with self._lock:
                self._current_job_id = None
            self.bump()
        if outcome.system_reason:
            self._last_probe = time.monotonic()
            self._set_system_reason(outcome.system_reason)
        return True

    def _sweep_refinements(self) -> None:
        now = time.monotonic()
        last = self._last_refinement_sweep
        if last is not None and now - last < REFINEMENT_SWEEP_SECONDS:
            return
        self._last_refinement_sweep = now
        schedule_refinements()

    def drain(self, max_batches: int = 10_000) -> int:
        """Run batches synchronously until there's no claimable work (tests, CLI)."""
        batches = 0
        while batches < max_batches and self.run_once():
            batches += 1
        return batches

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                worked = self.run_once()
            except Exception:
                logger.exception("Ingest worker iteration failed")
                worked = False
                self._stop.wait(5.0)
            if not worked and not self._stop.is_set():
                self._wake.wait(self._next_wait())
                self._wake.clear()

    def _next_wait(self) -> float:
        """Idle wait, cut short when a system-pause re-probe is due sooner."""
        if self._system_reason is None:
            return self._idle_wait
        until_probe = self._probe_interval - (time.monotonic() - self._last_probe)
        return max(0.05, min(self._idle_wait, until_probe))


_worker: IngestWorker | None = None


def get_ingest_worker() -> IngestWorker:
    """Process-wide worker instance (started by the FastAPI lifespan)."""
    global _worker
    if _worker is None:
        _worker = IngestWorker()
    return _worker
