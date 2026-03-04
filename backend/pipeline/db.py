"""Shared DB session helper for pipeline scripts."""

from contextlib import contextmanager

from backend.app.config import settings
from backend.app.models import get_engine, get_session_local


@contextmanager
def pipeline_db():
    """Yield a short-lived DB session for pipeline use.

    Commits automatically on clean exit; rolls back on exception.
    """
    engine = get_engine(settings.database_url)
    SessionLocal = get_session_local(engine)
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
