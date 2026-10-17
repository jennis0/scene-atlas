# Resource Management and Concurrency

## Overview

Scene Atlas runs on hardware from small laptops to servers, against libraries whose largest maps exceed 700 Mpx (gigabytes of RAM to decode). Image processing is the memory-heavy part: decoding, hashing, thumbnails, colour extraction, grid detection and embedding. Concurrency is bounded by five controls whose defaults are computed from the host at first boot, plus request-level limits on uploads.

## Concurrency Controls

| # | Control | Mechanism | Bounds | Setting |
|---|---------|-----------|--------|---------|
| 1 | Prepare pool | `ThreadPoolExecutor` (`prepare_pool.py`) | Images prepared in parallel, process-wide | `max_concurrent_prepare` |
| 2 | Heavy-op semaphore | `asyncio.Semaphore` on `app.state.heavy_op_semaphore` | Concurrent `upload_archive` / `seal_import` requests | `max_concurrent_heavy_requests` |
| 3 | JobRunner | `ThreadPoolExecutor` (`job_runner.py`) | Concurrent maintenance jobs | `max_job_workers` |
| 4 | IngestWorker | One thread (`pipeline/ingest_worker.py`) | One import batch at a time, process-wide | `ingestion_batch_size` (items per batch) |
| 5 | MemoryBudget | `threading.Condition` byte budget (`memory_budget.py`) | Total estimated decode memory across prepare workers | `ingest_memory_budget_mb` (env) |

### 1. Prepare pool

A single pool shared by everything that prepares images, so `max_concurrent_prepare` is a system-wide limit rather than a per-import multiplier. The IngestWorker submits each item of a batch to it (`prepare_item`: hash, decode, pixel hash, thumbnails, colours, perceptual hash, grid detection, copy to `.incoming/`). Created in the lifespan by `init_prepare_pool()`; `get_prepare_pool()` raises if it was not initialised.

### 2. Heavy-op semaphore

Gates the two import endpoints that do large amounts of synchronous work in `asyncio.to_thread()`: `PUT /imports/{job}/archives` (stream + expand a zip) and `POST /imports/{job}/seal` (free-space check + group planning). Applied with the `acquire_heavy_op` dependency (`api/dependencies.py`). Created in the lifespan because `asyncio.Semaphore()` needs a running loop on some platforms.

Per-file uploads (`PUT /imports/{job}/items/{item}/content`) do not take the semaphore: they stream to disk asynchronously and only hop to a thread for MIME verification and the row update.

Both endpoints take the semaphore (an async dependency) before the SQLite write lock, so they cannot deadlock against each other.

### SQLite write lock

Mutating import and group endpoints are decorated with `@write_locked` (`api/dependencies.py`), which takes `BEGIN IMMEDIATE` on the endpoint's own thread before the body runs, so a request can't fail on a stale snapshot while the IngestWorker commits. Taking the lock in a dependency instead held it while the request waited for a second thread-pool slot, and under load the waiters filled the pool. `upload_archive` takes the lock inside its worker thread for the same reason.

### 3. JobRunner

Runs user-triggered and startup maintenance jobs off the event loop: embedding rebuild, startup `reconcile_vectors`, retagging, grid backfill, model download/activation, library deletion. Tracks status, progress and results in memory (records kept for `job_retention_seconds`). Created eagerly in the lifespan via `get_job_runner()`, which reads `max_job_workers` from the DB. `shutdown_job_runner()` cancels queued jobs and waits for running ones; those stop at their next batch boundary (see [Cooperative shutdown](#cooperative-shutdown)). Imports do not run on the JobRunner. Scheduler tasks run in the asyncio default executor, not on the JobRunner.

### 4. IngestWorker

One daemon thread processes all imports: it claims up to `ingestion_batch_size` ready items round-robin across jobs, prepares them on the prepare pool, embeds the batch, commits in one `BEGIN IMMEDIATE` transaction and then writes vectors. Because there is only one claimer, two imports share the prepare pool rather than each adding threads. It pauses (stops claiming, re-probes every 30 s) when the embedding model is unavailable, the library folder is missing, or any ingest volume has under 512 MB free. Details in [ingestion.md](ingestion.md).

### 5. MemoryBudget

The prepare pool bounds how many images are processed at once, not how large they are. Before decoding, `prepare_item` estimates the item's peak memory from its header (`plan_decode`: dimensions, format, progressive JPEG, grid detection read size) and reserves it from the budget, blocking while the budget is exhausted. An item larger than the whole budget is admitted when nothing else holds a reservation, so it cannot deadlock.

Capacity: `ingest_memory_budget_mb` if set, otherwise half of total RAM beyond a 2 GiB reserve, minimum 1 GiB (`default_capacity_bytes()`; assumes 4 GiB if psutil is unavailable).

Related decode limits in `config.py`:
- `max_image_pixels` (1,000,000,000) — Pillow's decompression-bomb limit; larger images fail.
- `pixel_hash_max_pixels` (100,000,000) — JPEGs above this are decoded at reduced scale (libjpeg DCT scaling) and skip the pixel-hash duplicate check.

## Resource Detection

`resource_detector.compute_resource_defaults()` runs once, inside `seed_default_settings()` on first boot. It reads `os.cpu_count()` (fallback 2) and total RAM via psutil (fallback 4 GB):

```
available_gb = max(0.5, total_ram_gb - 2.0)     # reserve ~2 GB for model, LanceDB, Python
ram_cap      = max(1, int(available_gb / 0.5))   # ~500 MB per prepare worker

max_job_workers               = max(1, min(4, cpu // 2))
max_concurrent_prepare        = max(1, min(cpu, 8, ram_cap))
max_concurrent_heavy_requests = max(1, min(max(1, cpu // 2), 6))
```

| Host | CPUs | RAM | `max_job_workers` | `max_concurrent_prepare` | `max_concurrent_heavy_requests` |
|------|------|-----|-------------------|--------------------------|---------------------------------|
| Low-end laptop | 2 | 4 GB | 1 | 2 | 1 |
| Mid-range desktop | 8 | 16 GB | 4 | 8 | 4 |
| Server | 16 | 32 GB | 4 | 8 | 6 |

## Request Limits

| Limit | Default | Setting | Applies to |
|-------|---------|---------|-----------|
| Max files per import | 50,000 | `max_import_items` (env, `config.py`) | Manifest chunks of one job (413 when exceeded) |
| Max file size | 2 GiB | `max_import_file_size` | Manifest entries (oversized → failed item), per-file uploads, archive uploads, archive members |
| Max video size | 2 GiB | `max_video_file_size` | Per-file uploads of video items |
| Max entries per archive | 1,000 | `max_import_files` | Each uploaded zip (`check_zip_safety`) |
| Max uncompressed size per archive | 2 GiB | `max_import_total_size` | Each uploaded zip (`check_zip_safety`) |
| Free disk space at seal | needed bytes + margin | — | `seal_import` returns 507 if staging/library can't hold the import |

A zip that fails `check_zip_safety` becomes one failed `archive` item rather than an error response.

## Service Constants (env, `config.py`)

| Constant | Default | Used by |
|----------|---------|---------|
| `CLIP_TEXT_CACHE_MAX` | 256 | Text embedding LRU (`clip_service.py`) |
| `JOB_RETENTION_SECONDS` | 3600 | Finished JobRunner records (`job_runner.py`) |
| `INGEST_MEMORY_BUDGET_MB` | unset (automatic) | MemoryBudget |
| `MAX_IMPORT_ITEMS` | 50000 | Imports API |

## Settings Sources

- **`app_settings` table** — all concurrency settings, import limits and algorithm parameters. Seeded once by `seed_default_settings()` (resource defaults above, hardcoded values for the rest). Changed via `PATCH /api/v1/settings` in every deployment mode. `.env` is never used to seed it, so first boot behaves the same in all modes.
- **`config.py` / env** — infrastructure (paths, ports, CORS, rate limits) and service constants. Server and developer modes use `.env`; the Electron shell passes `--port`, `--app-data-dir` and `--image-library-dir` to the sidecar on its command line, and saves the setup wizard's WebP choice through the settings API.

| Setting | Default source | Takes effect |
|---------|---------------|--------------|
| `max_concurrent_prepare` | resource detector | Restart |
| `max_concurrent_heavy_requests` | resource detector | Restart |
| `max_job_workers` | resource detector | Restart |
| `scheduler_enabled` | `True` | Restart |
| `ingestion_batch_size` | 16 | Next batch (read per batch) |
| Import limits | hardcoded | Next request (read per request) |

The Settings UI exposes `max_concurrent_prepare` (labelled "Parallel image processing", 1–16; restart required); the others are only editable through the API.

## Memory Monitoring

The event-loop heartbeat (every 15 s, `main.py`) logs thread count and process RSS (`process_utils.get_rss_mb()`, `None` without psutil):

```
[heartbeat] event loop alive — threads=8, RSS=342 MB
```

This is diagnostic only. A `MemoryError` during preparation is classified by `pipeline/error_classifier.py` and recorded on the item. On non-Windows, SIGUSR1 logs a stack dump of every thread.

## Startup and Shutdown

In the `main.py` lifespan:
1. `seed_default_settings()` — computes and persists resource defaults on first boot.
2. `get_app_settings()` — reads the concurrency settings.
3. `init_prepare_pool(max_concurrent_prepare)`.
4. `asyncio.Semaphore(max_concurrent_heavy_requests)` → `app.state.heavy_op_semaphore`.
5. `get_job_runner()` — creates the JobRunner.
6. `ingest_worker.recover()` and `start()` (when `ingest_worker_enabled`).
7. Scheduler start (when `scheduler_enabled`), heartbeat start.

Shutdown: `request_shutdown()` → scheduler stop → `ingest_worker.stop(60s)` (the in-flight batch commits; anything left is recovered next start) → `shutdown_job_runner()` → `shutdown_prepare_pool()` → LanceDB shutdown. The MemoryBudget is created lazily on first use.

### Cooperative shutdown

JobRunner jobs and scheduler tasks run on pool threads that can't be killed, and the process waits for them on exit. `backend/app/services/shutdown.py` holds a process-wide signal: the lifespan clears it at startup and sets it first thing on shutdown (`JobRunner.shutdown()` sets it too). Long jobs call `raise_if_shutting_down()` at batch boundaries, after a batch has committed, which raises `ShutdownRequested`; the JobRunner records the job as `interrupted` and the scheduler doesn't record the run, so an overdue task runs again shortly after the next start.

| Job | Checks | Resumes by |
|---|---|---|
| `reconcile_vectors` | per delete chunk / re-embed batch | next run (startup, 24 h) sees what's still missing |
| `rebuild_all_embeddings` (also model activation) | per 32-image batch (it runs `reconcile_vectors`) | startup reconciliation re-embeds the images not yet in the new table |
| `backfill_grid_detection` | per image | next run picks up images without grid info (`force` starts over) |
| `retag_all_images`, `reparse_names`, `backfill_content_hash` | per batch | re-running (idempotent; content-hash backfill only selects missing hashes) |
| `export_library` (CLI) | per batch | re-running; an interrupted export has no `metadata.json` |
| `run_ingest_maintenance`, `sweep_orphaned_store_files` | between steps / stores | next scheduled run |

Not interruptible: `backup_database` (a partial backup could be rotated in as a good one), library purge (stopping half way leaves rows and files out of step), and model download (one `snapshot_download` call). The ZIP export endpoint is a streaming response, which uvicorn drains before the lifespan shutdown runs.

## Why Not Async SQLAlchemy

`aiosqlite` wraps synchronous `sqlite3` in a background thread, which is what FastAPI's threadpool already does for `def` endpoints. On SQLite it brings no practical benefit for a large migration. Revisit if Postgres is added.

## Key Files

| File | Responsibility |
|------|---------------|
| `backend/app/resource_detector.py` | `compute_resource_defaults()` |
| `backend/app/models/database.py` | `seed_default_settings()` |
| `backend/app/models/schemas.py` | `AppSettings` / `AppSettingsPatch` |
| `backend/app/services/app_settings.py` | Reads/writes settings rows |
| `backend/app/services/prepare_pool.py` | Shared prepare pool |
| `backend/app/services/memory_budget.py` | `MemoryBudget`, `get_memory_budget()` |
| `backend/app/services/job_runner.py` | `JobRunner` |
| `backend/pipeline/ingest_worker.py` | `IngestWorker` |
| `backend/pipeline/ingest_process.py` | `plan_decode`, `prepare_item`, `process_batch` |
| `backend/app/api/dependencies.py` | `acquire_heavy_op` |
| `backend/app/api/imports.py` | Request limits, seal free-space check |
| `backend/app/services/validation.py` | `check_zip_safety` |
| `backend/app/config.py` | Env settings and service constants |
| `backend/app/main.py` | Lifespan wiring, heartbeat |
| `backend/app/process_utils.py` | `get_rss_mb()` |
