"""Shared fixtures for the integration tests."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from backend.app.models import AppSetting
from backend.app.services import ingest_state as st
from backend.pipeline import ingest_worker
from backend.pipeline.ingest_worker import IngestWorker
from backend.pipeline.pipeline_config import PipelineConfig

BASE = "/api/v1/imports"


@pytest.fixture
def api(test_client, tmp_db, monkeypatch, lancedb_service):
    """The imports API (TestClient) with a worker driven synchronously by ``drain()``."""
    engine, SessionLocal = tmp_db
    monkeypatch.setattr(
        "backend.pipeline.tasks.embedding_generation.batch_generate_clip_embeddings",
        lambda paths, **kw: [[0.1] * 8 for _ in paths],
    )
    monkeypatch.setattr(st, "retry_delay", lambda attempts: timedelta(0))
    worker = IngestWorker(
        config_loader=lambda: PipelineConfig(
            enable_image_grid_detection=False, ingestion_batch_size=8
        ),
        probe=lambda: None,
        probe_interval=0.0,
    )
    monkeypatch.setattr(ingest_worker, "_worker", worker)

    class Api:
        client = test_client

        def __init__(self):
            self.SessionLocal = SessionLocal
            self.worker = worker
            self.vectors = lancedb_service

        def create(self, label="Test", image_type="battlemap"):
            r = self.client.post(BASE, json={"label": label, "default_image_type": image_type})
            assert r.status_code == 201, r.text
            return r.json()["id"]

        def manifest(self, job_id, files):
            r = self.client.post(f"{BASE}/{job_id}/manifest", json={"files": files})
            assert r.status_code == 200, r.text
            return r.json()

        def put(self, job_id, item_id, data: bytes):
            return self.client.put(f"{BASE}/{job_id}/items/{item_id}/content", content=data)

        def detail(self, job_id):
            r = self.client.get(f"{BASE}/{job_id}")
            assert r.status_code == 200, r.text
            return r.json()

        def set_app_setting(self, key, value):
            with self.SessionLocal() as db:
                row = db.query(AppSetting).filter_by(key=key).one()
                row.value_json = json.dumps(value)
                db.commit()

    return Api()
