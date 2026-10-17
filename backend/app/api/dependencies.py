"""Shared FastAPI dependencies for API route handlers."""

import functools

from fastapi import Request
from sqlalchemy.orm import Session

from ...pipeline.ingest_queue import begin_immediate
from ..models import get_session_local


def get_db(request: Request):
    """Dependency to get database session."""
    SessionLocal = get_session_local(request.app.state.db_engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


async def acquire_heavy_op(request: Request):
    """Admission control — limits concurrent heavy operations (import seal, archive expansion).

    Prevents GIL thrashing from too many concurrent asyncio.to_thread() calls.
    """
    semaphore = request.app.state.heavy_op_semaphore
    await semaphore.acquire()
    try:
        yield
    finally:
        semaphore.release()


def write_locked(endpoint):
    """Run a sync endpoint (taking ``db``) inside ``BEGIN IMMEDIATE``.

    The endpoint commits what it keeps; anything left open is rolled back. The
    lock is taken and released on the endpoint's own thread: taken in a
    dependency, it was held while the request waited for a second thread-pool
    slot, and under load the waiters filled the pool.
    """

    @functools.wraps(endpoint)
    def wrapper(*args, **kwargs):
        db: Session = kwargs["db"]
        begin_immediate(db)
        try:
            return endpoint(*args, **kwargs)
        finally:
            if db.in_transaction():
                db.rollback()

    return wrapper
