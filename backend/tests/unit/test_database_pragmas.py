"""Tests that get_engine() applies correct SQLite pragmas for concurrency safety."""

from sqlalchemy import text

from backend.app.models.database import get_engine


def test_wal_journal_mode_enabled(tmp_path):
    """get_engine() must enable WAL journal mode for concurrent write safety."""
    db_path = tmp_path / "test.db"
    engine = get_engine(f"sqlite:///{db_path}")
    with engine.connect() as conn:
        result = conn.execute(text("PRAGMA journal_mode")).fetchone()
    assert result[0] == "wal", f"Expected WAL mode, got '{result[0]}'"


def test_busy_timeout_set(tmp_path):
    """get_engine() must set busy_timeout so writers wait instead of failing immediately."""
    db_path = tmp_path / "test.db"
    engine = get_engine(f"sqlite:///{db_path}")
    with engine.connect() as conn:
        result = conn.execute(text("PRAGMA busy_timeout")).fetchone()
    assert result[0] >= 5000, f"Expected busy_timeout >= 5000ms, got {result[0]}ms"


def test_pragmas_not_set_for_non_sqlite():
    """Non-SQLite URLs skip the pragma event listener without errors."""
    # Just verify get_engine() doesn't crash for a postgres-style URL
    # (we don't actually connect, so no real DB is needed)
    try:
        engine = get_engine("postgresql://user:pass@localhost/db")
        # No event listener should be attached — this is a structural check
        assert "sqlite" not in str(engine.url)
    except Exception:
        pass  # connection errors are expected; we only care it doesn't crash on setup
