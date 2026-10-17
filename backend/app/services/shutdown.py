"""Process-wide shutdown signal for long-running background work.

JobRunner jobs and scheduler tasks run on threads that shutdown can't kill, so
the process waits for them. Long jobs call :func:`raise_if_shutting_down` at
batch boundaries (after committing a batch) and stop there, leaving state a
later run picks up. The lifespan sets the signal first thing on shutdown.
"""

import threading

_requested = threading.Event()


class ShutdownRequested(Exception):
    """Raised at a batch boundary once shutdown has begun. Work already committed is kept."""


def request_shutdown() -> None:
    _requested.set()


def clear_shutdown() -> None:
    """Reset the signal (app startup; tests)."""
    _requested.clear()


def shutdown_requested() -> bool:
    return _requested.is_set()


def raise_if_shutting_down() -> None:
    if _requested.is_set():
        raise ShutdownRequested("Interrupted by shutdown")
