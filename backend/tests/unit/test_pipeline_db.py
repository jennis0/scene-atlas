"""Tests for the pipeline_db() session helper."""

import pytest
from sqlalchemy.orm import Session


def test_pipeline_db_yields_session():
    """pipeline_db() yields a SQLAlchemy Session."""
    from backend.pipeline.db import pipeline_db

    with pipeline_db() as db:
        assert isinstance(db, Session)


def test_pipeline_db_commits_on_success(tmp_path, monkeypatch):
    """Changes made inside pipeline_db() are committed on clean exit."""
    from backend.app.config import settings
    from backend.app.models import get_engine, get_session_local, init_db
    from backend.app.models.database import ImportJob
    from backend.pipeline.db import pipeline_db

    db_url = f"sqlite:///{tmp_path}/pipe_test.db"
    engine = get_engine(db_url)
    init_db(engine)
    monkeypatch.setattr(settings, "database_url", db_url)

    with pipeline_db() as db:
        job = ImportJob(id="pipe-1", status="staging", source_label="test")
        db.add(job)

    # Verify committed with a fresh session
    SessionLocal = get_session_local(engine)
    verify_db = SessionLocal()
    try:
        row = verify_db.query(ImportJob).filter(ImportJob.id == "pipe-1").first()
        assert row is not None
        assert row.status == "staging"
    finally:
        verify_db.close()


def test_pipeline_db_rolls_back_on_exception(tmp_path, monkeypatch):
    """Exceptions inside pipeline_db() cause a rollback, not a commit."""
    from backend.app.config import settings
    from backend.app.models import get_engine, get_session_local, init_db
    from backend.app.models.database import ImportJob
    from backend.pipeline.db import pipeline_db

    db_url = f"sqlite:///{tmp_path}/pipe_test2.db"
    engine = get_engine(db_url)
    init_db(engine)
    monkeypatch.setattr(settings, "database_url", db_url)

    with pytest.raises(RuntimeError), pipeline_db() as db:
        job = ImportJob(id="pipe-2", status="staging", source_label="test")
        db.add(job)
        raise RuntimeError("simulated failure")

    # Verify NOT committed
    SessionLocal = get_session_local(engine)
    verify_db = SessionLocal()
    try:
        row = verify_db.query(ImportJob).filter(ImportJob.id == "pipe-2").first()
        assert row is None
    finally:
        verify_db.close()
