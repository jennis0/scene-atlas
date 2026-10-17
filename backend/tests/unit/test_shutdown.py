"""Long jobs stop at batch boundaries once shutdown begins (backend/app/services/shutdown.py)."""

import asyncio
import threading

import pytest

from backend.app.services.job_runner import JobRunner
from backend.app.services.scheduler import Scheduler
from backend.app.services.shutdown import (
    ShutdownRequested,
    raise_if_shutting_down,
    request_shutdown,
)


def test_job_runner_shutdown_interrupts_a_running_job():
    started = threading.Event()
    batches = []

    def long_job():
        started.set()
        while True:
            raise_if_shutting_down()
            batches.append(1)
            threading.Event().wait(0.01)

    runner = JobRunner(max_workers=1)
    job_id = runner.submit(long_job, name="long")
    assert started.wait(5)

    stopper = threading.Thread(target=runner.shutdown)
    stopper.start()
    stopper.join(5)
    assert not stopper.is_alive(), "shutdown waited for a job that should have stopped"

    record = runner.get_job(job_id)
    assert record is not None
    assert record.status == "interrupted"
    assert batches


def test_runner_reports_shutting_down_from_the_process_signal():
    runner = JobRunner(max_workers=1)
    try:
        assert not runner.shutting_down
        request_shutdown()
        assert runner.shutting_down
    finally:
        runner.shutdown()


@pytest.mark.asyncio
async def test_interrupted_scheduled_task_is_not_recorded(tmp_path):
    ran = threading.Event()

    def task():
        ran.set()
        raise ShutdownRequested("Interrupted by shutdown")

    scheduler = Scheduler(tmp_path, startup_grace=0.01)
    scheduler.register(task, hours=1, name="interrupted")
    await scheduler.start()
    for _ in range(100):
        if ran.is_set():
            break
        await asyncio.sleep(0.02)
    await scheduler.stop()
    assert ran.is_set()
    assert scheduler.last_run("interrupted") is None
