"""When an import's grouping phase runs (ADR-028, design/ingestion.md §5.8): which jobs are
due, one run per job at a time, waiting while the model is busy, and the triggers."""

from __future__ import annotations

import threading
from datetime import timedelta

import pytest

from backend.app.models import ImportItem, ImportJob
from backend.app.services import ingest_state as st
from backend.pipeline import group_jobs as gj
from backend.pipeline import ingest_queue as q
from backend.pipeline.group_jobs import GroupingScheduler, Outcome, Readiness


@pytest.fixture
def db_url(tmp_db, monkeypatch):
    engine, SessionLocal = tmp_db
    monkeypatch.setattr("backend.app.config.settings.database_url", str(engine.url))
    return SessionLocal


def make_job(SessionLocal, *, planned=True, states=(st.DONE,), grouped=False, created=0) -> str:
    with SessionLocal() as db:
        job = q.create_job(db)
        job.created_at = q.utcnow() + timedelta(seconds=created)
        for i, state in enumerate(states):
            db.add(
                ImportItem(
                    job_id=job.id,
                    kind="image",
                    relative_path=f"A/{i}.png",
                    filename=f"{i}.png",
                    image_type="battlemap",
                    state=state,
                )
            )
        if planned:
            job.planned_at = q.utcnow()
        if grouped:
            job.grouped_at = q.utcnow()
        db.flush()
        q.recompute_job_status(db, job.id)
        db.commit()
        return job.id


def status(SessionLocal, job_id: str) -> str:
    with SessionLocal() as db:
        return db.get_one(ImportJob, job_id).status


def test_a_settled_job_is_grouping_until_grouped(db_url):
    assert status(db_url, make_job(db_url, states=(st.DONE, st.FAILED))) == st.JOB_GROUPING
    assert status(db_url, make_job(db_url, grouped=True)) == st.JOB_COMPLETED


def test_due_jobs_are_sealed_settled_and_ungrouped(db_url):
    due = make_job(db_url, states=(st.DONE, st.FAILED, st.SKIPPED, st.DUPLICATE))
    cancelled = make_job(db_url, states=(st.SKIPPED,), created=1)
    with db_url() as db:
        db.get_one(ImportJob, cancelled).status = st.JOB_CANCELLED
        db.commit()
    make_job(db_url, planned=False)
    make_job(db_url, states=(st.DONE, st.READY))
    make_job(db_url, states=(st.PROCESSING,))
    make_job(db_url, grouped=True)
    with db_url() as db:
        assert gj.due_jobs(db) == [due, cancelled]  # oldest first; cancelled ones too
        assert gj.due_jobs(db, [cancelled, "nope"]) == [cancelled]


def test_a_job_with_open_items_again_is_no_longer_grouped(db_url):
    job_id = make_job(db_url, states=(st.FAILED,), grouped=True)
    assert status(db_url, job_id) == st.JOB_COMPLETED
    with db_url() as db:
        q.retry_items(db, job_id)
        db.commit()
        job = db.get_one(ImportJob, job_id)
        assert job.status == st.JOB_ACTIVE and job.grouped_at is None


def test_scheduling_runs_each_due_job_once(db_url):
    first, second = make_job(db_url), make_job(db_url, created=1)
    ran: list[str] = []
    scheduler = GroupingScheduler(lambda job_id, run: ran.append(job_id))
    assert scheduler.schedule() == [first, second]
    assert scheduler.schedule([second]) == []  # still running (the runner never ran them)
    assert ran == [first, second]


def test_a_job_already_running_is_not_started_twice(db_url, monkeypatch):
    job_id = make_job(db_url)
    started, release = threading.Event(), threading.Event()

    def slow(job_id_, progress_fn=None, *, readiness):
        started.set()
        release.wait(5)
        return Outcome.GROUPED

    monkeypatch.setattr(gj, "group_job", slow)
    scheduler = GroupingScheduler(lambda j, run: threading.Thread(target=run, args=(j,)).start())
    assert scheduler.schedule() == [job_id]
    assert started.wait(5)
    assert scheduler.running() == {job_id}
    assert scheduler.schedule() == []
    release.set()
    for _ in range(200):
        if not scheduler.running():
            break
        threading.Event().wait(0.01)
    assert scheduler.running() == set()


def test_a_failed_run_is_logged_and_can_run_again(db_url, monkeypatch, caplog):
    job_id = make_job(db_url)

    def broken(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(gj, "group_job", broken)
    scheduler = GroupingScheduler.inline(lambda: Readiness.OFF)
    assert scheduler.schedule() == [job_id]
    assert "Grouping import" in caplog.text
    assert scheduler.running() == set()


def test_runs_go_to_the_job_runner_hidden_from_the_background_jobs_dock(monkeypatch):
    submitted: list[tuple] = []

    class Runner:
        def submit(self, fn, *args, name=None, **kwargs):
            submitted.append((args, name))

    monkeypatch.setattr("backend.app.services.job_runner.get_job_runner", lambda: Runner())
    gj._job_runner("0123456789abcdef", lambda job_id: Outcome.GROUPED)
    ((args, name),) = submitted
    assert args == ("0123456789abcdef",) and name.startswith("Import")


def test_a_waiting_run_leaves_the_job_due(db_url):
    job_id = make_job(db_url)
    assert gj.group_job(job_id, readiness=lambda: Readiness.DEFER) == Outcome.DEFERRED
    with db_url() as db:
        assert gj.due_jobs(db) == [job_id]


def test_unknown_or_unsettled_jobs_are_not_due(db_url):
    open_job = make_job(db_url, states=(st.READY,))
    for job_id in ("nope", open_job):
        assert gj.group_job(job_id, readiness=lambda: Readiness.OFF) == Outcome.NOT_DUE


@pytest.mark.parametrize(
    ("held", "loading", "reason", "expected"),
    [
        (True, False, None, Readiness.DEFER),
        (False, True, "Waiting for the AI model to load", Readiness.DEFER),
        (False, False, "No AI model is available", Readiness.OFF),
        (False, False, None, Readiness.USE),
    ],
)
def test_readiness_follows_the_model(monkeypatch, held, loading, reason, expected):
    class Worker:
        def is_held(self):
            return held

    monkeypatch.setattr("backend.pipeline.ingest_worker.get_ingest_worker", lambda: Worker())
    monkeypatch.setattr("backend.app.services.clip_service.is_clip_loading", lambda: loading)
    monkeypatch.setattr(
        "backend.app.services.clip_service.get_clip_unavailable_reason", lambda: reason
    )
    assert gj.embedding_readiness() == expected


def _config():
    from backend.pipeline.pipeline_config import PipelineConfig

    return PipelineConfig(enable_image_grid_detection=False, ingestion_batch_size=4)


def test_the_idle_worker_sweeps_for_grouping(monkeypatch):
    from backend.pipeline import ingest_worker

    sweeps: list[None] = []
    monkeypatch.setattr(ingest_worker, "schedule_grouping", lambda: sweeps.append(None))
    monkeypatch.setattr(ingest_worker, "claim_next_batch", lambda cursor, limit: (None, []))
    worker = ingest_worker.IngestWorker(probe=lambda: None, config_loader=_config)
    assert worker.run_once() is False
    assert worker.run_once() is False
    assert len(sweeps) == 2


def test_a_held_worker_does_not_sweep(monkeypatch):
    from backend.pipeline import ingest_worker

    sweeps: list[None] = []
    monkeypatch.setattr(ingest_worker, "schedule_grouping", lambda: sweeps.append(None))
    worker = ingest_worker.IngestWorker(probe=lambda: None, config_loader=_config)
    with worker.held("Paused while the search model changes"):
        assert worker.is_held() and worker.run_once() is False
    assert sweeps == []


def test_maintenance_sweeps_for_grouping(monkeypatch):
    from backend.pipeline import ingest_maintenance

    for step in (
        "abandon_stale_uploads",
        "expire_finished_jobs",
        "release_staged_bytes",
        "prune_dismissed_jobs",
        "sweep_stray_staging_files",
    ):
        monkeypatch.setattr(ingest_maintenance, step, lambda: 0)
    monkeypatch.setattr(ingest_maintenance, "schedule_grouping", lambda: ["a", "b"])
    assert ingest_maintenance.run_ingest_maintenance()["grouping"] == 2
