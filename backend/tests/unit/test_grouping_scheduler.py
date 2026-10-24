"""When an import's grouping phase runs (ADR-028, design/ingestion.md §5.8): which jobs are
due, one run per job at a time, waiting while the model is busy or vectors are missing, bounded
retries, and the triggers."""

from __future__ import annotations

import logging
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
                    parsed="{}",
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


def test_a_job_with_open_items_again_is_no_longer_grouped(db_url):
    job_id = make_job(db_url, states=(st.FAILED,), grouped=True)
    assert status(db_url, job_id) == st.JOB_COMPLETED
    with db_url() as db:
        q.retry_items(db, job_id)
        db.commit()
        job = db.get_one(ImportJob, job_id)
        assert job.status == st.JOB_ACTIVE and job.grouped_at is None


def inline(readiness=lambda: Readiness.OFF) -> GroupingScheduler:
    return GroupingScheduler(runner=lambda job_id, run: run(job_id), readiness=readiness)


def test_scheduling_runs_each_due_job_once(db_url):
    first, second = make_job(db_url), make_job(db_url, created=1)
    ran: list[str] = []
    scheduler = GroupingScheduler(lambda job_id, run: ran.append(job_id))
    assert scheduler.schedule() == [first, second]
    assert scheduler.schedule() == []  # still running (the runner never ran them)
    assert ran == [first, second]


def test_a_job_already_running_is_not_started_twice(db_url, monkeypatch):
    job_id = make_job(db_url)
    started, release = threading.Event(), threading.Event()
    threads: list[threading.Thread] = []

    def slow(job_id_, progress_fn=None, **_kwargs):
        started.set()
        release.wait(5)
        return Outcome.DEFERRED

    def runner(job_id_, run):
        threads.append(threading.Thread(target=run, args=(job_id_,)))
        threads[-1].start()

    monkeypatch.setattr(gj, "group_job", slow)
    scheduler = GroupingScheduler(runner)
    assert scheduler.schedule() == [job_id]
    assert started.wait(5)
    assert scheduler.schedule() == []
    release.set()
    threads[0].join(5)
    assert scheduler.schedule() == [job_id]  # finished (and still due): it can run again
    threads[1].join(5)


def test_a_job_whose_grouping_keeps_failing_is_grouped_by_its_paths(db_url, monkeypatch, caplog):
    """Each sweep would retry a broken run for ever, the import's images hidden: after a few
    failures the job is grouped by its file paths alone, without content."""
    caplog.set_level(logging.INFO)
    job_id = make_job(db_url)

    def broken(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(gj, "_proposals", broken)
    scheduler = inline()
    for _ in range(gj._MAX_FAILED_RUNS):
        assert scheduler.schedule() == [job_id]
    with db_url() as db:
        assert db.get_one(ImportJob, job_id).grouped_at is None
    assert scheduler.schedule() == [job_id]
    with db_url() as db:
        assert db.get_one(ImportJob, job_id).status == st.JOB_COMPLETED
        assert {i.import_group_id is not None for i in db.query(ImportItem)} == {True}
    errors = [r for r in caplog.records if r.levelname == "ERROR"]
    assert len(errors) == gj._MAX_FAILED_RUNS
    assert "grouped by its file paths alone" in errors[-1].getMessage()
    assert "paths only" in caplog.text


def test_a_job_whose_paths_only_grouping_fails_too_is_left_alone(db_url, monkeypatch):
    job_id = make_job(db_url)

    def broken(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(gj, "_proposals", broken)
    monkeypatch.setattr(gj, "_parsed_proposals", broken)
    scheduler = inline()
    for _ in range(gj._MAX_FAILED_RUNS + 1):
        assert scheduler.schedule() == [job_id]
    assert scheduler.schedule() == []
    with db_url() as db:
        assert gj.due_jobs(db) == [job_id]  # a restart tries again


def test_a_run_waits_for_missing_vectors_a_few_minutes(db_url, monkeypatch):
    """Timed from the first run that waited, not counted in sweeps (a sweep follows every
    batch, so counted waits could all pass in seconds)."""
    job_id = make_job(db_url)
    now = [1000.0]
    waits: list[bool] = []

    def no_vectors(job_id_, progress_fn=None, *, wait_for_vectors, **_kwargs):
        waits.append(wait_for_vectors)
        return Outcome.NO_VECTORS if wait_for_vectors else Outcome.GROUPED

    monkeypatch.setattr(gj, "group_job", no_vectors)
    scheduler = GroupingScheduler(
        runner=lambda j, run: run(j), readiness=lambda: Readiness.OFF, clock=lambda: now[0]
    )
    for _ in range(20):  # many sweeps in no time
        assert scheduler.schedule() == [job_id]
    now[0] += gj._VECTOR_WAIT_SECONDS - 1
    assert scheduler.schedule() == [job_id]
    assert waits == [True] * 21
    now[0] += 1
    assert scheduler.schedule() == [job_id]
    assert waits[-1] is False


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
