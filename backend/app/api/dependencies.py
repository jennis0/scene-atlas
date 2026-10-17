"""Shared FastAPI dependencies for API route handlers."""

from fastapi import Request

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


def get_write_db(request: Request):
    """A session whose transaction holds the SQLite write lock from the start.

    Use for endpoints that read, check, then write: concurrent requests are
    serialised instead of all passing the check.
    """
    db = get_session_local(request.app.state.db_engine)()
    try:
        begin_immediate(db)
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
