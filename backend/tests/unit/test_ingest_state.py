"""Tests for the per-item ingest state machines (backend/app/services/ingest_state.py)."""

from datetime import timedelta

import pytest

from backend.app.services import ingest_state as st
from backend.app.services.ingest_state import IllegalTransitionError, ItemEvent

# Every legal transition, from design/ingest-redesign.md §4.1.
LEGAL = [
    (st.AWAITING_BYTES, ItemEvent.BYTES_RECEIVED, st.READY),
    (st.AWAITING_BYTES, ItemEvent.HASH_DUPLICATE, st.DUPLICATE),
    (st.AWAITING_BYTES, ItemEvent.FILE_ERROR, st.FAILED),
    (st.AWAITING_BYTES, ItemEvent.SKIP, st.SKIPPED),
    (st.READY, ItemEvent.CLAIM, st.PROCESSING),
    (st.READY, ItemEvent.SKIP, st.SKIPPED),
    (st.PROCESSING, ItemEvent.COMMITTED, st.DONE),
    (st.PROCESSING, ItemEvent.DUPLICATE_AT_COMMIT, st.DUPLICATE),
    (st.PROCESSING, ItemEvent.FILE_ERROR, st.FAILED),
    (st.PROCESSING, ItemEvent.TRANSIENT_RETRY, st.READY),
    (st.PROCESSING, ItemEvent.GIVE_UP, st.FAILED),
    (st.PROCESSING, ItemEvent.SYSTEM_ERROR, st.READY),
    (st.PROCESSING, ItemEvent.BYTES_LOST, st.AWAITING_BYTES),
    (st.PROCESSING, ItemEvent.RECOVERED, st.READY),
    (st.PROCESSING, ItemEvent.CRASH_LIMIT, st.FAILED),
    (st.FAILED, ItemEvent.RETRY, st.READY),
    (st.FAILED, ItemEvent.RETRY_NEEDS_BYTES, st.AWAITING_BYTES),
    (st.DUPLICATE, ItemEvent.IMPORT_AS_COPY, st.READY),
    (st.DUPLICATE, ItemEvent.IMPORT_AS_COPY_NEEDS_BYTES, st.AWAITING_BYTES),
]


@pytest.mark.parametrize(("state", "event", "expected"), LEGAL)
def test_legal_transitions(state, event, expected):
    assert st.next_item_state(state, event) == expected


def test_every_other_combination_is_illegal():
    legal = {(state, event) for state, event, _ in LEGAL}
    for state in st.ITEM_STATES:
        for event in ItemEvent:
            if (state, event) in legal:
                continue
            with pytest.raises(IllegalTransitionError):
                st.next_item_state(state, event)


def test_done_and_skipped_are_final():
    for event in ItemEvent:
        for state in (st.DONE, st.SKIPPED):
            with pytest.raises(IllegalTransitionError):
                st.next_item_state(state, event)


def test_processing_can_never_be_skipped():
    """Cancel lets the in-flight batch finish; it never yanks a processing item."""
    assert st.PROCESSING not in st.sources_for(ItemEvent.SKIP)


def test_sources_for_matches_table():
    assert st.sources_for(ItemEvent.SKIP) == {st.AWAITING_BYTES, st.READY}
    assert st.sources_for(ItemEvent.CLAIM) == {st.READY}
    assert st.sources_for(ItemEvent.RETRY) == {st.FAILED}


def test_every_event_has_one_target():
    for event in ItemEvent:
        assert st.target_of(event) in st.ITEM_STATES


def test_retry_delay_grows():
    assert st.retry_delay(1) == timedelta(seconds=5)
    assert st.retry_delay(2) == timedelta(seconds=20)
    assert st.retry_delay(3) == timedelta(seconds=80)


class TestComputeJobStatus:
    def test_unplanned_job_is_active_even_with_no_items(self):
        assert st.compute_job_status(st.JOB_ACTIVE, False, {}) == st.JOB_ACTIVE

    def test_planned_with_open_items_is_active(self):
        counts = {st.READY: 1, st.DONE: 3}
        assert st.compute_job_status(st.JOB_ACTIVE, True, counts) == st.JOB_ACTIVE

    def test_planned_with_no_open_items_completes(self):
        counts = {st.DONE: 3, st.FAILED: 1, st.DUPLICATE: 2, st.SKIPPED: 1}
        assert st.compute_job_status(st.JOB_ACTIVE, True, counts) == st.JOB_COMPLETED

    def test_failures_never_fail_the_job(self):
        assert st.compute_job_status(st.JOB_ACTIVE, True, {st.FAILED: 5}) == st.JOB_COMPLETED

    def test_all_duplicates_completes(self):
        """Regression: a re-import of files already in the library used to stick in staging."""
        counts = {st.DUPLICATE: 12}
        assert st.compute_job_status(st.JOB_ACTIVE, True, counts) == st.JOB_COMPLETED

    def test_awaiting_bytes_keeps_job_open(self):
        counts = {st.AWAITING_BYTES: 2, st.DONE: 8}
        assert st.compute_job_status(st.JOB_ACTIVE, True, counts) == st.JOB_ACTIVE

    def test_paused_stays_paused_while_open(self):
        assert st.compute_job_status(st.JOB_PAUSED, True, {st.READY: 4}) == st.JOB_PAUSED

    def test_paused_with_nothing_open_completes(self):
        assert st.compute_job_status(st.JOB_PAUSED, True, {st.DONE: 4}) == st.JOB_COMPLETED

    def test_cancelled_is_sticky(self):
        assert st.compute_job_status(st.JOB_CANCELLED, True, {st.READY: 4}) == st.JOB_CANCELLED

    def test_completed_reopens_when_items_retried(self):
        assert st.compute_job_status(st.JOB_COMPLETED, True, {st.READY: 1}) == st.JOB_ACTIVE
