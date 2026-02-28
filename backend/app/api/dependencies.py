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
