# Testing Strategy

For how to run tests and operational details, see [docs/development/testing.md](../docs/development/testing.md).

## Overview

Backend tests live in `backend/tests/unit/` and `backend/tests/integration/`; frontend tests are Vitest files next to the code in `frontend/src/`; end-to-end tests are Playwright specs in `e2e/tests/`.

**No infrastructure required.** Backend tests run against a temporary SQLite database and temporary directories. LanceDB does not create files on import, so nothing is patched at import time; tests that touch vectors replace `get_lancedb_service()` per test with a fake (see `FakeVectors` in `test_ingest_pipeline.py` / `test_imports_api.py`, `_FakeLanceDB` in `test_search_characterisation.py`).

Tests marked `heavy` (real CLIP ONNX model) are excluded by default (`addopts = -m 'not heavy'` in `pyproject.toml`); run them with `-m heavy`.

## Where checks run

| Stage | Defined in | Runs |
|---|---|---|
| Pre-commit (local) | `.husky/pre-commit` | `lint-staged` on staged files |
| Pre-push (local) | `.husky/pre-push` | ruff check + format check (`backend/`, `scripts/`), pyright, backend unit tests, ESLint, Prettier check, `tsc --noEmit`, knip, Vitest, Electron `tsc`, jscpd duplication threshold |
| Pull request to `main` | `.github/workflows/ci.yml` | `backend-security` (pip-audit, bandit; non-blocking), `backend-integration` (unit + integration tests with coverage, small ONNX model), `frontend-build` (`npm run build`), `quality` (pyright, knip, jscpd) |
| Release (manual `workflow_dispatch`) | `.github/workflows/release.yml` | full backend suite incl. heavy tests, frontend lint/tests/coverage/build, backend unit tests on Windows and macOS, Playwright E2E, Electron builds per platform, optional publish |

CI does not run lint or unit-only jobs on PRs; the pre-push hook is relied on for those (skippable with `git push --no-verify`).

## Coverage Thresholds

- **Backend**: 40% line coverage (`pyproject.toml [tool.coverage.report] fail_under`)
- **Frontend**: 20% line coverage (`frontend/vitest.config.ts`, `@vitest/coverage-v8`)
- Ratchet these up as coverage improves.

## Shared fixtures (`backend/tests/conftest.py`)

| Fixture | Provides |
|---|---|
| `prepare_pool_fixture` (autouse) | Fresh prepare pool (2 workers) per test, shut down afterwards |
| `tmp_db` | `(engine, SessionLocal)` for a fresh SQLite DB in `tmp_path`, schema created and tag categories seeded |
| `db_session` | A session on `tmp_db`, closed after the test |
| `query_counter` | `QueryCounter` on the test engine: `with query_counter as q: ...; q.count` / `q.selects("images")`. Used in `test_query_counts.py` to pin query counts against N+1 regressions |
| `make_test_image` | Factory writing a small JPEG to a given path |
| `test_client` | FastAPI `TestClient` bound to `tmp_db`, with storage paths and image/thumbnail store singletons redirected to `tmp_path`, rate limiting disabled, and `settings.ingest_worker_enabled = False` |

## Conventions

### Test images

Generate programmatically with `make_test_image` or PIL/numpy (e.g. `image_bytes()` in `test_ingest_pipeline.py`). Never commit binary image blobs.

### Database isolation

Each test gets its own SQLite DB via `tmp_db`. The FastAPI lifespan sets `app.state.db_engine` to the configured database, so `test_client` sets `settings.database_url` before entering the `TestClient` and overrides `app.state.db_engine` **after** entering it.

Code that opens its own sessions from `settings.database_url` is pointed at the test DB with:

```python
monkeypatch.setattr("backend.app.config.settings.database_url", str(engine.url))
```

### Driving the ingest worker

Pipeline design: [ingestion.md](ingestion.md).

The background ingest thread is never started in tests. Tests construct an `IngestWorker` with a fixed `PipelineConfig`, a probe that reports no system pause, and `probe_interval=0.0`, then call `worker.drain()`, which runs batches synchronously until no work is claimable and returns the batch count:

```python
worker = IngestWorker(
    config_loader=lambda: PipelineConfig(enable_image_grid_detection=False, ingestion_batch_size=4),
    probe=lambda: None,
    probe_interval=0.0,
)
...
assert worker.drain() >= 1
```

Alongside this, ingest tests fake `get_lancedb_service` (in `backend.pipeline.ingest_process` and wherever else it is imported), replace `batch_generate_clip_embeddings` with constant vectors, set `ingest_state.retry_delay` to zero, and swap `services._image_store` / `services._thumbnail_store` for `ImageStore`s under `tmp_path`. API tests additionally set `backend.pipeline.ingest_worker._worker` to the test worker so endpoints and the test share it (`test_imports_api.py`).

### Mocking the JobRunner

Endpoints that submit background jobs (model switching, some image operations) are tested with the JobRunner mocked at the import site:

```python
mock_runner = MagicMock()
monkeypatch.setattr("backend.app.api.models.get_job_runner", lambda: mock_runner)
```

### Schema drift

`backend/tests/unit/test_schema_drift.py` compares the ORM metadata against a database built by the Alembic migrations (`alembic.autogenerate.compare_metadata`). Any difference not in its `ACCEPTED` set fails, so a new column, index or constraint must be added to both the models and a migration.

### Search golden tests

`backend/tests/integration/test_search_characterisation.py` builds a deterministic library, replaces the CLIP and LanceDB services with deterministic fakes, and compares the full responses of `/search/`, `/search/groups` and `/search/facets` (ordering, totals, scores, mosaics) against `backend/tests/integration/golden/search_responses.json`. When a behaviour change is intended, regenerate and review the diff:

```bash
UPDATE_SEARCH_GOLDEN=1 uv run python -m pytest backend/tests/integration/test_search_characterisation.py
```

## What to test when adding new features

| Change | Tests to add/update |
|---|---|
| New parser rule | `unit/test_parser.py` |
| New Pydantic schema | `unit/test_schemas.py` -- defaults, round-trip, serialization |
| New model column / index | Alembic migration; `unit/test_schema_drift.py` must stay green |
| New API endpoint | New or existing file in `integration/` using `test_client` |
| Ingest pipeline change | `integration/test_ingest_pipeline.py` (worker + `drain()`), `unit/test_ingest_state.py` for state transitions |
| Search behaviour change | `integration/test_search_endpoint.py`; regenerate the golden file if responses change intentionally |
| New list/search query | `integration/test_query_counts.py` to pin the query count |
| New user-facing flow | `e2e/tests/` -- Playwright spec exercising the UI flow |

## Known quirks

- **TestClient lifespan override.** The FastAPI lifespan sets `app.state.db_engine` from settings. Fixtures override it **after** `TestClient.__enter__()`.
- **Store singletons.** `services._image_store` / `services._thumbnail_store` may already be cached at the real library path by an earlier test; fixtures replace them rather than relying on settings alone.
- **Exit code 134 in CI.** Native libraries can abort during interpreter shutdown after all tests pass; `ci.yml` and the integration step in `release.yml` tolerate exit code 134.
