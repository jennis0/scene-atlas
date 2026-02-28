# Plan: Remove Prefect, Replace with In-Process Job Runner

## Goal

Strip all Prefect infrastructure (server, Postgres, Redis, worker, deploy script) and replace
with a lightweight in-process `JobRunner` that lives inside the FastAPI process. This eliminates
4 Docker containers and 1 background process while preserving all processing logic unchanged.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  FastAPI Process                                         │
│                                                          │
│  API endpoints ──submit()──▶ JobRunner                   │
│                              │                           │
│                              ├─ ThreadPoolExecutor(N)    │
│                              │   (bounded worker threads)│
│                              │                           │
│                              ├─ Shared CLIP model        │
│                              │   (loaded once at startup)│
│                              │                           │
│                              └─ Job queue (in-memory)    │
│                                                          │
│  CLI scripts ──call functions directly──▶ same logic     │
└─────────────────────────────────────────────────────────┘

Docker containers: Qdrant only (optional)
```

**Key design decisions:**
- `ThreadPoolExecutor` with configurable `max_workers` (default 2) for true concurrency
- CLIP model is thread-safe for inference — shared across all workers
- Within each job, `prepare_single_image` uses its own bounded thread pool for
  concurrent image preparation (thumbnails, colors, grid detection)
- SQLite writes remain batched and sequential (one writer at a time is fine for batched inserts)
- Job queue is in-memory (acceptable: jobs are short-lived, progress is in DB, and
  if the process crashes, restarting is the right recovery anyway)

## Scope

### Files to CREATE (2 new files)

1. **`backend/app/services/job_runner.py`** — The replacement for Prefect
   - `JobRunner` class with `ThreadPoolExecutor(max_workers=N)`
   - `submit(fn, *args, **kwargs) -> job_id` — submit a callable for background execution
   - `submit_sync(fn, *args, **kwargs) -> result` — run synchronously, wait for result
     (replaces `run_deployment(..., timeout=120)` for `analyse_upload`)
   - Singleton `get_job_runner()` accessor
   - Startup/shutdown hooks (create pool, drain on shutdown)
   - Config: `max_job_workers` added to Settings (default 2)

2. **`backend/app/services/scheduler.py`** — Replaces Prefect scheduled deployments
   - Lightweight scheduler using `threading.Timer` or `asyncio` loop
   - Runs `backup_database()` daily and `cleanup_staging()` every 6 hours
   - Started in FastAPI lifespan, stopped on shutdown

### Files to MODIFY (significant changes)

3. **`backend/flows/ingestion.py`** — Remove Prefect decorators, replace `.submit()` concurrency
   - Strip `@flow` and `@task` decorators from all functions
   - Replace `prepare_single_image.submit()` with `concurrent.futures.ThreadPoolExecutor`
     (local pool within `_run_group`, not the JobRunner pool)
   - Replace `batch_save_to_database(...)` / `batch_save_to_qdrant(...)` task calls
     with direct function calls (they're already plain functions under the decorator)
   - Add simple retry wrapper for functions that had `retries=N`
   - `analyse_upload` becomes a regular function called directly by the upload endpoint
   - `process_import_job` / `process_import_group` become regular functions submitted to JobRunner

4. **`backend/app/api/imports.py`** — Replace `run_deployment()` with JobRunner
   - `upload_files`: call `analyse_upload()` directly (it's fast, no CLIP) instead of
     `run_deployment(..., timeout=120)`. Run in executor to avoid blocking the event loop.
   - `confirm_import`: `job_runner.submit(process_import_group, ...)` instead of `run_deployment()`
   - `confirm_all_groups`: `job_runner.submit(process_import_job, ...)` instead of `run_deployment()`
   - Remove `from prefect.deployments import run_deployment`

5. **`backend/app/api/tags.py`** — Replace `run_deployment()` with JobRunner
   - `trigger_retag_all`: `job_runner.submit(retag_all_images)` instead of `run_deployment()`
   - Remove Prefect import

6. **`backend/app/main.py`** — Remove Prefect env setup, add JobRunner + scheduler lifecycle
   - Remove `os.environ.setdefault("PREFECT_API_URL", ...)`
   - In lifespan startup: initialize JobRunner, start scheduler
   - In lifespan shutdown: shutdown JobRunner (drain queue), stop scheduler
   - Add JobRunner health to `/health` endpoint (report queue depth, active workers)

7. **`backend/app/config.py`** — Add new settings, remove Prefect settings
   - Add: `max_job_workers: int = 2`, `scheduler_enabled: bool = True`
   - Remove: all `prefect_*` settings (prefect_api_url, prefect_work_pool, all deployment names)

### Files to MODIFY (minor — strip decorators only)

8. **`backend/flows/tasks/embedding_generation.py`** — Remove `@task` decorator, keep functions
9. **`backend/flows/tasks/color_extraction.py`** — Remove `@task` decorator
10. **`backend/flows/tasks/image_processing.py`** — Remove `@task` decorator
11. **`backend/flows/tasks/grid_detection.py`** — Remove `@task` decorator

### Files to MODIFY (one-off scripts — strip decorators, keep CLI entry points)

12. **`backend/flows/retag_all_images.py`** — Remove `@flow`/`@task`, keep `if __name__`
13. **`backend/flows/backfill_content_hash.py`** — Remove `@flow`/`@task`, keep `if __name__`
14. **`backend/flows/backfill_grid_detection.py`** — Remove `@flow`/`@task`, keep `if __name__`
15. **`backend/flows/write_new_embeddings.py`** — Remove `@flow`/`@task`, keep `if __name__`
16. **`backend/flows/reparse_names.py`** — Remove `@flow`/`@task`, keep `if __name__`
17. **`backend/flows/maintenance.py`** — Remove `@flow`/`@task`, keep functions, add `if __name__`

### Files to MODIFY (logging)

18. **`backend/flows/logger.py`** — Remove Prefect logger, use standard Python logging
    - `get_logger()` becomes just `logging.getLogger(name)`
    - All existing call sites (`get_logger(__name__)`) continue to work unchanged

### Files to DELETE

19. **`backend/flows/deploy.py`** — Prefect deployment registration (no longer needed)

### Files to MODIFY (infrastructure)

20. **`docker-compose.yml`** — Remove postgres, redis, prefect-server, prefect-services.
    Keep only qdrant.
21. **`scripts/start.py`** — Remove Prefect worker spawn and wait. Just: docker compose up, start API.
22. **`scripts/stop.py`** — Remove worker PID kill. Just: stop API, docker compose stop.

### Files to MODIFY (tests)

23. **`backend/tests/integration/test_confirm_endpoint.py`** — Mock `job_runner.submit()`
    instead of `run_deployment()`
24. **`backend/tests/integration/test_upload_endpoint.py`** — Mock direct `analyse_upload()`
    call instead of `run_deployment()`

## Implementation Order

### Phase 1: Create the JobRunner (no existing behavior changes yet)
- Create `backend/app/services/job_runner.py`
- Create `backend/app/services/scheduler.py`
- Add new config settings to `backend/app/config.py`

### Phase 2: Strip Prefect from task modules (low risk, mechanical)
- Update `backend/flows/logger.py`
- Strip `@task` from all `backend/flows/tasks/*.py` files
- Strip `@flow`/`@task` from all one-off scripts in `backend/flows/`
- Delete `backend/flows/deploy.py`

### Phase 3: Rewire ingestion.py (core change)
- Replace `.submit()` concurrency with `concurrent.futures.ThreadPoolExecutor`
- Strip all decorators
- Add retry helper for tasks that had retries

### Phase 4: Rewire API endpoints (integration point)
- Update `imports.py` to use JobRunner
- Update `tags.py` to use JobRunner
- Update `main.py` lifespan (start/stop JobRunner + scheduler)
- Remove Prefect env var setup

### Phase 5: Infrastructure cleanup
- Slim down `docker-compose.yml`
- Simplify `scripts/start.py` and `scripts/stop.py`
- Remove Prefect config from `backend/app/config.py`

### Phase 6: Fix tests
- Update mocks in integration tests

### Phase 7: Verify
- Run backend tests

## What Stays Exactly the Same

- All processing logic: `_run_group()`, `_process_batch()`, `prepare_single_image()`, etc.
- All DB operations: `_save_image_to_db()`, `batch_save_to_database()`, etc.
- Progress tracking: `update_import_group_job_progress()` writes to ImportGroupJob
- Frontend: zero changes (polls same `/imports/status/{job_id}` endpoint)
- Qdrant: unchanged (still optional, still degrades gracefully)
- CLIP: unchanged (singleton, pre-loaded at startup)
- All one-off CLI scripts: still runnable with `uv run python -m backend.flows.<name>`

## What Gets Removed

- 4 Docker containers (postgres, redis, prefect-server, prefect-services)
- 1 background process (prefect worker)
- `deploy.py` script
- All Prefect Python dependencies (prefect, prefect-redis)
- ~10 config settings (prefect_api_url, work pool, deployment names)
