"""Tests for the periodic task scheduler (backend/app/services/scheduler.py)."""

import asyncio
import time

import pytest

from backend.app.services.scheduler import Scheduler


def test_first_run_after_grace_when_never_run(tmp_path):
    scheduler = Scheduler(tmp_path, startup_grace=60)
    assert scheduler.first_delay("backup", 24 * 3600) == 60


def test_overdue_task_runs_after_grace(tmp_path):
    """Regression (audit M12): short desktop sessions never reached the interval."""
    (tmp_path / "backup.last_run").write_text(str(time.time() - 30 * 3600))
    scheduler = Scheduler(tmp_path, startup_grace=60)
    assert scheduler.first_delay("backup", 24 * 3600) == 60


def test_recent_task_waits_for_remaining_interval(tmp_path):
    (tmp_path / "backup.last_run").write_text(str(time.time() - 3600))
    scheduler = Scheduler(tmp_path, startup_grace=60)
    delay = scheduler.first_delay("backup", 24 * 3600)
    assert 22.9 * 3600 < delay <= 23 * 3600


def test_corrupt_marker_treated_as_never_run(tmp_path):
    (tmp_path / "backup.last_run").write_text("not a number")
    assert Scheduler(tmp_path, startup_grace=5).first_delay("backup", 3600) == 5


def test_without_state_dir_every_start_is_a_first_run():
    assert Scheduler(None, startup_grace=7).first_delay("x", 3600) == 7


@pytest.mark.asyncio
async def test_runs_task_and_records_last_run(tmp_path):
    calls = []
    scheduler = Scheduler(tmp_path, startup_grace=0.01)
    scheduler.register(lambda: calls.append(1), hours=1, name="tick")
    await scheduler.start()
    for _ in range(100):
        if calls:
            break
        await asyncio.sleep(0.02)
    await scheduler.stop()
    assert calls == [1]
    assert scheduler.last_run("tick") is not None


@pytest.mark.asyncio
async def test_failing_task_does_not_record_or_stop_scheduler(tmp_path):
    def boom():
        raise RuntimeError("nope")

    scheduler = Scheduler(tmp_path, startup_grace=0.01)
    scheduler.register(boom, hours=1, name="boom")
    await scheduler.start()
    await asyncio.sleep(0.1)
    await scheduler.stop()
    assert scheduler.last_run("boom") is None
