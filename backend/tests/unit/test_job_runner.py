"""Dismissing background jobs from the activity dock."""

import threading

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import jobs as jobs_api
from backend.app.services.job_runner import JobRunner


@pytest.fixture
def runner():
    runner = JobRunner(max_workers=2)
    yield runner
    runner.shutdown()


def _wait_finished(runner: JobRunner, job_id: str) -> None:
    for _ in range(500):
        record = runner.get_job(job_id)
        if record and record.status in ("completed", "failed"):
            return
        threading.Event().wait(0.01)
    raise AssertionError("job didn't finish")


def _boom():
    raise RuntimeError("boom")


def test_dismiss_removes_only_finished_jobs(runner):
    release = threading.Event()
    running = runner.submit(release.wait, name="running")
    done = runner.submit(lambda: 1, name="done")
    _wait_finished(runner, done)

    assert runner.dismiss(running) is False
    assert runner.dismiss(done) is True
    assert runner.dismiss(done) is None
    assert [j.id for j in runner.list_jobs()] == [running]
    release.set()


def test_dismiss_finished_keeps_active_jobs(runner):
    release = threading.Event()
    running = runner.submit(release.wait, name="running")
    finished = [runner.submit(lambda: 1, name="ok"), runner.submit(_boom, name="fails")]
    for job_id in finished:
        _wait_finished(runner, job_id)

    assert runner.dismiss_finished() == 2
    assert [j.id for j in runner.list_jobs()] == [running]
    release.set()


def test_dismiss_endpoints(runner, monkeypatch):
    monkeypatch.setattr(jobs_api, "get_job_runner", lambda: runner)
    app = FastAPI()
    app.include_router(jobs_api.router, prefix="/jobs")
    client = TestClient(app)

    release = threading.Event()
    running = runner.submit(release.wait, name="running")
    done = runner.submit(lambda: 1, name="done")
    _wait_finished(runner, done)

    assert client.post(f"/jobs/{running}/dismiss").status_code == 409
    assert client.post("/jobs/unknown/dismiss").status_code == 404
    assert client.post(f"/jobs/{done}/dismiss").json() == {"dismissed": 1}
    assert client.post("/jobs/dismiss-finished").json() == {"dismissed": 0}
    assert [j["id"] for j in client.get("/jobs/").json()] == [running]
    release.set()
