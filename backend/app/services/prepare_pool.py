"""Global shared ThreadPoolExecutor for image prepare steps.

All import jobs share this pool so max_concurrent_prepare acts as a
system-wide limit, not a per-job multiplier. A single import gets
full throughput; two concurrent imports share the budget.

Initialised at lifespan startup after AppSettings are loaded.
Shutdown at lifespan teardown.
"""

import logging
import threading
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

_pool: ThreadPoolExecutor | None = None
_lock = threading.Lock()


def init_prepare_pool(max_workers: int) -> None:
    """Create the global pool. Call once at startup."""
    global _pool
    with _lock:
        if _pool is not None:
            return
        _pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="prepare")
        logger.info("Prepare pool started with max_workers=%d", max_workers)


def get_prepare_pool() -> ThreadPoolExecutor:
    """Return the global pool. Raises if not initialised."""
    if _pool is None:
        raise RuntimeError("Prepare pool not initialised — call init_prepare_pool() first")
    return _pool


def shutdown_prepare_pool(wait: bool = True) -> None:
    """Shut down the pool at application exit."""
    global _pool
    with _lock:
        if _pool is not None:
            _pool.shutdown(wait=wait)
            _pool = None
            logger.info("Prepare pool stopped")
