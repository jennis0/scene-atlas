"""Shared FastAPI dependencies for API route handlers."""

from fastapi import Request

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
    """Admission control — limits concurrent heavy operations (analyse, confirm-all).

    Prevents GIL thrashing from too many concurrent asyncio.to_thread() calls.
    """
    semaphore = request.app.state.heavy_op_semaphore
    await semaphore.acquire()
    try:
        yield
    finally:
        semaphore.release()
