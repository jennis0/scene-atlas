"""Unit tests for the import job state machine (transition_job_status).

Tests every transition path, terminal idempotency, completed_at timestamping,
and the pending_groups / all_confirmed interaction.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.models.database import Base, ImportGroupJob, ImportJob
from backend.app.services.import_state import (
    GROUP_TERMINAL_STATUSES,
    TERMINAL_STATUSES,
    transition_job_status,
)


@pytest.fixture
def db():
    """In-memory SQLite session for fast unit tests."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _make_job(db, job_id, status="staging", pending_groups=0, all_confirmed=False):
    job = ImportJob(
        id=job_id,
        status=status,
        total_files=1,
        source_label="test",
        pending_groups=pending_groups,
        all_confirmed=all_confirmed,
    )
    db.add(job)
    db.flush()
    return job


def _make_group(db, job_id, group_id, status="running"):
    gj = ImportGroupJob(
        id=group_id,
        job_id=job_id,
        group_name=f"Group {group_id}",
        author="TestAuthor",
        total_files=1,
        processed_files=0,
        failed_files=0,
        status=status,
    )
    db.add(gj)
    db.flush()
    return gj


# ---------------------------------------------------------------------------
# Missing / unknown job
# ---------------------------------------------------------------------------


class TestMissingJob:
    def test_unknown_job_returns_unknown(self, db):
        assert transition_job_status(db, "nonexistent") == "unknown"


# ---------------------------------------------------------------------------
# Terminal idempotency
# ---------------------------------------------------------------------------


class TestTerminalIdempotency:
    @pytest.mark.parametrize("status", sorted(TERMINAL_STATUSES))
    def test_terminal_status_is_idempotent(self, db, status):
        """Once a job is terminal, transition_job_status is a no-op."""
        job = _make_job(db, f"term-{status}", status=status)
        original_updated_at = job.updated_at

        result = transition_job_status(db, job.id)

        assert result == status
        assert job.status == status
        # updated_at should NOT change — no transition happened
        assert job.updated_at == original_updated_at


# ---------------------------------------------------------------------------
# No groups → stay in current status
# ---------------------------------------------------------------------------


class TestNoGroups:
    @pytest.mark.parametrize("status", ["uploading", "staging", "active"])
    def test_no_groups_stays_in_current_status(self, db, status):
        """Without group jobs, the job stays in its current non-terminal status."""
        _make_job(db, f"no-groups-{status}", status=status)
        result = transition_job_status(db, f"no-groups-{status}")
        assert result == status


# ---------------------------------------------------------------------------
# Running groups → active
# ---------------------------------------------------------------------------


class TestRunningGroups:
    def test_single_running_group_sets_active(self, db):
        _make_job(db, "j1", status="staging")
        _make_group(db, "j1", "g1", status="running")

        result = transition_job_status(db, "j1")
        assert result == "active"

    def test_mix_of_running_and_completed_stays_active(self, db):
        _make_job(db, "j2", status="active")
        _make_group(db, "j2", "g1", status="completed")
        _make_group(db, "j2", "g2", status="running")

        result = transition_job_status(db, "j2")
        assert result == "active"

    def test_running_with_failures_stays_active(self, db):
        _make_job(db, "j3", status="active")
        _make_group(db, "j3", "g1", status="failed")
        _make_group(db, "j3", "g2", status="running")

        result = transition_job_status(db, "j3")
        assert result == "active"


# ---------------------------------------------------------------------------
# All terminal groups, no pending → completed or failed
# ---------------------------------------------------------------------------


class TestAllTerminalNoPending:
    def test_all_completed_sets_completed(self, db):
        _make_job(db, "j1", status="active")
        _make_group(db, "j1", "g1", status="completed")
        _make_group(db, "j1", "g2", status="completed")

        result = transition_job_status(db, "j1")
        assert result == "completed"

    def test_all_completed_sets_completed_at(self, db):
        job = _make_job(db, "j2", status="active")
        _make_group(db, "j2", "g1", status="completed")
        assert job.completed_at is None

        transition_job_status(db, "j2")
        assert job.completed_at is not None
        # completed_at should be approximately now
        assert (datetime.now(UTC).replace(tzinfo=None) - job.completed_at) < timedelta(seconds=5)

    def test_any_failure_sets_failed(self, db):
        _make_job(db, "j3", status="active")
        _make_group(db, "j3", "g1", status="completed")
        _make_group(db, "j3", "g2", status="failed")

        result = transition_job_status(db, "j3")
        assert result == "failed"

    def test_all_failed_sets_failed(self, db):
        _make_job(db, "j4", status="active")
        _make_group(db, "j4", "g1", status="failed")
        _make_group(db, "j4", "g2", status="failed")

        result = transition_job_status(db, "j4")
        assert result == "failed"

    def test_cancelled_groups_count_as_terminal(self, db):
        """Cancelled groups are terminal — if all groups are cancelled with
        no failures, the job completes."""
        _make_job(db, "j5", status="active")
        _make_group(db, "j5", "g1", status="cancelled")

        result = transition_job_status(db, "j5")
        assert result == "completed"

    def test_mix_cancelled_and_completed(self, db):
        _make_job(db, "j6", status="active")
        _make_group(db, "j6", "g1", status="completed")
        _make_group(db, "j6", "g2", status="cancelled")

        result = transition_job_status(db, "j6")
        assert result == "completed"

    def test_all_confirmed_flag_irrelevant_without_pending(self, db):
        """When pending_groups=0, all_confirmed doesn't matter."""
        _make_job(db, "j7", status="active", all_confirmed=False)
        _make_group(db, "j7", "g1", status="completed")

        result = transition_job_status(db, "j7")
        assert result == "completed"


# ---------------------------------------------------------------------------
# All terminal groups + pending → awaiting_input
# ---------------------------------------------------------------------------


class TestAwaitingInput:
    def test_pending_groups_triggers_awaiting_input(self, db):
        _make_job(db, "j1", status="active", pending_groups=2)
        _make_group(db, "j1", "g1", status="completed")

        result = transition_job_status(db, "j1")
        assert result == "awaiting_input"

    def test_awaiting_input_does_not_set_completed_at(self, db):
        """awaiting_input is non-terminal — completed_at stays None."""
        job = _make_job(db, "j2", status="active", pending_groups=1)
        _make_group(db, "j2", "g1", status="completed")

        transition_job_status(db, "j2")
        assert job.completed_at is None

    def test_all_confirmed_overrides_pending(self, db):
        """If all_confirmed=True, pending_groups is ignored → completes."""
        _make_job(db, "j3", status="active", pending_groups=2, all_confirmed=True)
        _make_group(db, "j3", "g1", status="completed")

        result = transition_job_status(db, "j3")
        assert result == "completed"

    def test_pending_with_failures_awaits_input(self, db):
        """Even with failures, if there are pending groups, await user input."""
        _make_job(db, "j4", status="active", pending_groups=1)
        _make_group(db, "j4", "g1", status="failed")

        result = transition_job_status(db, "j4")
        assert result == "awaiting_input"

    def test_awaiting_input_to_active_on_new_running(self, db):
        """If user confirms another group and it starts running,
        awaiting_input → active."""
        _make_job(db, "j5", status="awaiting_input", pending_groups=1)
        _make_group(db, "j5", "g1", status="completed")
        _make_group(db, "j5", "g2", status="running")

        result = transition_job_status(db, "j5")
        assert result == "active"

    def test_awaiting_input_to_completed_when_pending_zeroed(self, db):
        """Once pending_groups is zeroed and all groups terminal → completed."""
        _make_job(db, "j6", status="awaiting_input", pending_groups=0)
        _make_group(db, "j6", "g1", status="completed")
        _make_group(db, "j6", "g2", status="completed")

        result = transition_job_status(db, "j6")
        assert result == "completed"


# ---------------------------------------------------------------------------
# updated_at is always set on transition
# ---------------------------------------------------------------------------


class TestUpdatedAt:
    def test_transition_sets_updated_at(self, db):
        job = _make_job(db, "j1", status="active")
        _make_group(db, "j1", "g1", status="completed")
        original = job.updated_at

        transition_job_status(db, "j1")
        assert job.updated_at is not None
        assert job.updated_at != original

    def test_no_op_for_terminal_does_not_update(self, db):
        job = _make_job(db, "j2", status="completed")
        original = job.updated_at

        transition_job_status(db, "j2")
        assert job.updated_at == original


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_single_completed_group_no_pending_completes(self, db):
        """Single group, no pending → completed (the base case)."""
        _make_job(db, "j1", status="active")
        _make_group(db, "j1", "g1", status="completed")

        result = transition_job_status(db, "j1")
        assert result == "completed"

    def test_group_terminal_constants_correct(self):
        """Sanity: group terminal statuses match expectations."""
        assert GROUP_TERMINAL_STATUSES == {"completed", "failed", "cancelled"}

    def test_job_terminal_constants_correct(self):
        """Sanity: job terminal statuses match expectations."""
        assert TERMINAL_STATUSES == {"completed", "failed", "cancelled", "expired", "broken"}

    def test_many_groups_all_completed(self, db):
        """Stress test: many groups all completed."""
        _make_job(db, "j1", status="active")
        for i in range(20):
            _make_group(db, "j1", f"g{i}", status="completed")

        result = transition_job_status(db, "j1")
        assert result == "completed"

    def test_status_from_staging_to_active_with_running_group(self, db):
        """First confirm starts a group → staging → active."""
        _make_job(db, "j1", status="staging", pending_groups=2)
        _make_group(db, "j1", "g1", status="running")

        result = transition_job_status(db, "j1")
        assert result == "active"

    def test_completed_at_only_set_once(self, db):
        """If somehow called twice on a freshly-terminal job, completed_at
        doesn't change (because the second call hits the terminal guard)."""
        job = _make_job(db, "j1", status="active")
        _make_group(db, "j1", "g1", status="completed")

        transition_job_status(db, "j1")
        first_completed = job.completed_at
        assert first_completed is not None

        # Second call — job is now terminal, should be a no-op
        result = transition_job_status(db, "j1")
        assert result == "completed"
        assert job.completed_at == first_completed
