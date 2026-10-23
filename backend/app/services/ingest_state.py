"""Item and job state machines for the per-item ingest pipeline (ADR-018).

Pure functions and constants only: no database access. The transition table
here is the single source of truth: database code asks ``sources_for(event)``
which states an event may be applied from, and uses that in its WHERE clauses,
so illegal transitions can't be written.

See design/ingestion.md §4 for the diagrams.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from enum import StrEnum

# Item states

AWAITING_BYTES = "awaiting_bytes"
READY = "ready"
PROCESSING = "processing"
DONE = "done"
DUPLICATE = "duplicate"
FAILED = "failed"
SKIPPED = "skipped"

ITEM_STATES = (AWAITING_BYTES, READY, PROCESSING, DONE, DUPLICATE, FAILED, SKIPPED)
OPEN_ITEM_STATES = frozenset({AWAITING_BYTES, READY, PROCESSING})
TERMINAL_ITEM_STATES = frozenset({DONE, DUPLICATE, FAILED, SKIPPED})

# An item that has been claimed this many times without finishing is failed:
# a file that crashes the process must not crash-loop the app forever.
MAX_ATTEMPTS = 3

# Job states

JOB_ACTIVE = "active"
JOB_PAUSED = "paused"
# Every file settled; the grouping phase is identifying the job's groups (ADR-028)
JOB_GROUPING = "grouping"
JOB_COMPLETED = "completed"
JOB_CANCELLED = "cancelled"

JOB_STATES = (JOB_ACTIVE, JOB_PAUSED, JOB_GROUPING, JOB_COMPLETED, JOB_CANCELLED)


class ItemEvent(StrEnum):
    """Everything that can happen to an item."""

    BYTES_RECEIVED = "bytes_received"  # upload landed and validated
    HASH_DUPLICATE = "hash_duplicate"  # byte hash matched a library image before processing
    CLAIM = "claim"  # worker took it
    COMMITTED = "committed"  # image row written
    DUPLICATE_AT_COMMIT = "duplicate_at_commit"  # source/stored/pixel hash matched at commit
    FILE_ERROR = "file_error"  # the file itself is bad
    TRANSIENT_RETRY = "transient_retry"  # temporary error, attempts remain
    GIVE_UP = "give_up"  # temporary error, attempts exhausted
    SYSTEM_ERROR = "system_error"  # queue pauses, item goes back
    BYTES_LOST = "bytes_lost"  # staged file missing; needs re-upload
    SOURCE_UNAVAILABLE = "source_unavailable"  # local import's folder is missing; job waits
    SOURCE_CHANGED = "source_changed"  # a linked file changed while it was read; read it again
    RECOVERED = "recovered"  # startup: was processing when the process died
    CRASH_LIMIT = "crash_limit"  # startup: was processing, attempts exhausted
    RETRY = "retry"  # user retry, staged bytes present
    RETRY_NEEDS_BYTES = "retry_needs_bytes"  # user retry, staged bytes gone
    IMPORT_AS_COPY = "import_as_copy"  # user override of a duplicate, bytes present
    IMPORT_AS_COPY_NEEDS_BYTES = "import_as_copy_needs_bytes"
    SKIP = "skip"  # cancel, finish-without, skip group, abandoned upload
    SORTED_OUT = "sorted_out"  # Auto: the image-type head says token/asset/other (design §5.6)
    REFRESH_GONE = "refresh_gone"  # a linked image being refreshed was removed meanwhile
    INCLUDE = "include"  # user override of a sorted-out item, bytes present
    INCLUDE_NEEDS_BYTES = "include_needs_bytes"


_TRANSITIONS: dict[tuple[str, ItemEvent], str] = {
    (AWAITING_BYTES, ItemEvent.BYTES_RECEIVED): READY,
    (AWAITING_BYTES, ItemEvent.HASH_DUPLICATE): DUPLICATE,
    (AWAITING_BYTES, ItemEvent.FILE_ERROR): FAILED,  # bytes received but invalid
    (AWAITING_BYTES, ItemEvent.SKIP): SKIPPED,
    (READY, ItemEvent.CLAIM): PROCESSING,
    (READY, ItemEvent.SKIP): SKIPPED,
    (PROCESSING, ItemEvent.COMMITTED): DONE,
    (PROCESSING, ItemEvent.DUPLICATE_AT_COMMIT): DUPLICATE,
    (PROCESSING, ItemEvent.FILE_ERROR): FAILED,
    (PROCESSING, ItemEvent.TRANSIENT_RETRY): READY,
    (PROCESSING, ItemEvent.GIVE_UP): FAILED,
    (PROCESSING, ItemEvent.SYSTEM_ERROR): READY,
    (PROCESSING, ItemEvent.BYTES_LOST): AWAITING_BYTES,
    (PROCESSING, ItemEvent.SOURCE_UNAVAILABLE): READY,
    (PROCESSING, ItemEvent.SOURCE_CHANGED): READY,
    (PROCESSING, ItemEvent.RECOVERED): READY,
    (PROCESSING, ItemEvent.CRASH_LIMIT): FAILED,
    (PROCESSING, ItemEvent.SORTED_OUT): SKIPPED,
    (PROCESSING, ItemEvent.REFRESH_GONE): SKIPPED,
    (FAILED, ItemEvent.RETRY): READY,
    (FAILED, ItemEvent.RETRY_NEEDS_BYTES): AWAITING_BYTES,
    (DUPLICATE, ItemEvent.IMPORT_AS_COPY): READY,
    (DUPLICATE, ItemEvent.IMPORT_AS_COPY_NEEDS_BYTES): AWAITING_BYTES,
    # Only for items skipped by SORTED_OUT (error_kind "sorted_out"); the queue checks that.
    (SKIPPED, ItemEvent.INCLUDE): READY,
    (SKIPPED, ItemEvent.INCLUDE_NEEDS_BYTES): AWAITING_BYTES,
}


class IllegalTransitionError(ValueError):
    """Raised when an event is applied to an item in a state that doesn't allow it."""


def next_item_state(state: str, event: ItemEvent) -> str:
    """Return the state an item moves to when ``event`` happens in ``state``."""
    try:
        return _TRANSITIONS[(state, event)]
    except KeyError:
        raise IllegalTransitionError(f"Cannot apply {event} to an item in state {state}") from None


def sources_for(event: ItemEvent) -> frozenset[str]:
    """States from which ``event`` is legal. Used in database WHERE clauses."""
    return frozenset(state for (state, ev) in _TRANSITIONS if ev == event)


def target_of(event: ItemEvent) -> str:
    """The single state ``event`` leads to (every event has exactly one target)."""
    targets = {target for (_, ev), target in _TRANSITIONS.items() if ev == event}
    if len(targets) != 1:
        raise RuntimeError(f"{event} has ambiguous targets {targets}")
    return targets.pop()


def retry_delay(attempts: int) -> timedelta:
    """Backoff before a transient failure is retried: 5 s, 20 s, 80 s, ..."""
    return timedelta(seconds=5 * 4 ** max(0, attempts - 1))


def compute_job_status(
    current: str, planned: bool, counts: Mapping[str, int], grouped: bool = True
) -> str:
    """Derive a job's status from its control state, item counts and whether its grouping
    phase has run.

    - ``cancelled`` is sticky (a cancelled job is still grouped, see ``group_jobs``).
    - A planned job with no open items (nothing awaiting bytes, ready or processing) is
      ``grouping`` until its grouping phase has run, then ``completed``, even if it was
      paused.
    - Otherwise a paused job stays paused and everything else is active. A finished job
      that gets open items again (retry) re-opens to active.
    """
    if current == JOB_CANCELLED:
        return JOB_CANCELLED
    open_count = sum(counts.get(state, 0) for state in OPEN_ITEM_STATES)
    if planned and open_count == 0:
        return JOB_COMPLETED if grouped else JOB_GROUPING
    if current == JOB_PAUSED:
        return JOB_PAUSED
    return JOB_ACTIVE
