# Resource Management

## Overview

Scene Atlas runs on hardware ranging from 2 GB laptops to 32 GB servers. Import processing is memory-intensive -- decompressing large battlemap images, generating thumbnails, running CLIP inference, and detecting grids can consume hundreds of MB per image. Without resource management, concurrent imports on a low-RAM machine cause OOM crashes.

The system uses three concurrency controls (admission semaphore, prepare pool, job runner) whose defaults are computed from the host's CPU count and RAM at first boot.

## Resource Detection

`resource_detector.py` runs once during `seed_default_settings()` on first boot. It reads:

- **CPU count** via `os.cpu_count()` (fallback: 2)
- **Total RAM** via `psutil.virtual_memory().total` (fallback: 4 GB if psutil unavailable)

### Default Computation Formula

```
available_gb = max(0.5, total_ram_gb - 2.0)     # reserve ~2 GB for CLIP, LanceDB, Python
ram_cap      = max(1, int(available_gb / 0.5))   # ~500 MB per prepare worker

max_job_workers              = max(1, min(4, cpu // 2))
max_concurrent_prepare       = max(1, min(cpu, 8, ram_cap))
max_concurrent_heavy_requests = max(1, min(max(1, cpu // 2), 6))
```

**Example outputs:**

| Host | CPUs | RAM | `max_job_workers` | `max_concurrent_prepare` | `max_concurrent_heavy_requests` |
|------|------|-----|-------------------|--------------------------|---------------------------------|
| Low-end laptop | 2 | 4 GB | 1 | 2 | 1 |
| Mid-range desktop | 8 | 16 GB | 4 | 8 | 4 |
| Server | 16 | 32 GB | 4 | 8 | 6 |

## Three Concurrency Controls

### 1. Admission Semaphore (`heavy_op_semaphore`)

**What:** An `asyncio.Semaphore` that gates entry into expensive async-to-thread operations (import analysis, confirm-all).

**Why:** Prevents GIL thrashing from too many concurrent `asyncio.to_thread()` calls. Without this, multiple users confirming imports simultaneously would saturate the event loop.

**Configured by:** `max_concurrent_heavy_requests` app setting.

**Created in:** `main.py` lifespan, stored on `app.state.heavy_op_semaphore`.

**Used via:** `acquire_heavy_op` FastAPI dependency in `dependencies.py`.

### 2. Prepare Pool (`PreparePoolService`)

**What:** A global `ThreadPoolExecutor` shared across all import jobs for CPU-heavy image preparation (thumbnails, color extraction, grid detection).

**Why:** Without a shared pool, each concurrent import would create its own threads, multiplying memory usage. A single import gets full throughput; two concurrent imports share the budget.

**Configured by:** `max_concurrent_prepare` app setting.

**Created in:** `main.py` lifespan via `init_prepare_pool(max_workers)`.

**Used via:** `get_prepare_pool()` in pipeline code.

### 3. Job Runner (`JobRunner`)

**What:** A `ThreadPoolExecutor` for background jobs (imports, retagging, embedding rebuilds, backfills). Tracks job status, progress, and results in memory.

**Why:** Heavy processing must not block the async event loop. The thread pool provides bounded concurrency for long-running work. Default of 2 workers allows one import + one maintenance job simultaneously.

**Configured by:** `max_job_workers` app setting.

**Created in:** Lazily on first call to `get_job_runner()`, reads `max_job_workers` from DB.

**Lifecycle:** `shutdown_job_runner()` called during lifespan teardown. Sets `_shutting_down` event so worker threads can bail out of long-running loops via `is_shutting_down()`.

## Configuration

All three concurrency settings are stored in the `app_settings` DB table and seeded by `seed_default_settings()` on first boot using values from `compute_resource_defaults()`.

| Setting | Default Source | Controls | Restart Required |
|---------|---------------|----------|-----------------|
| `max_concurrent_prepare` | `min(cpu, 8, ram_cap)` | Prepare pool thread count | Yes |
| `max_concurrent_heavy_requests` | `min(cpu // 2, 6)` | Admission semaphore permits | Yes |
| `max_job_workers` | `min(4, cpu // 2)` | Job runner thread count | Yes |
| `scheduler_enabled` | `True` | Whether periodic maintenance runs | Yes |

Users can adjust `max_concurrent_prepare` via the Settings UI ("Concurrent imports" slider, 1-16). The other values are currently only editable via the `PATCH /api/v1/settings` API.

## Memory Monitoring

The event loop heartbeat (every 15 seconds in `main.py`) logs the process RSS alongside active thread count:

```
[heartbeat] event loop alive -- threads=8, RSS=342 MB
```

RSS is read via `psutil.Process().memory_info().rss` in `process_utils.py`. Returns `None` if psutil is unavailable (graceful degradation).

This is diagnostic-only -- there is no automated action on high memory. Operators monitor logs or health endpoints to tune concurrency settings if RSS grows too large.

## Startup Sequence

Resource-related initialization in `main.py` lifespan:

1. `seed_default_settings()` -- computes and persists resource defaults on first boot
2. `get_app_settings()` -- reads `max_concurrent_prepare` and `max_concurrent_heavy_requests` from DB
3. `init_prepare_pool(max_concurrent_prepare)` -- creates the shared thread pool
4. `asyncio.Semaphore(max_concurrent_heavy_requests)` -- creates admission control, stored on `app.state`
5. `get_job_runner()` -- lazily creates the job runner thread pool (reads `max_job_workers` from DB)
6. Heartbeat task starts -- logs RSS every 15 seconds

On shutdown: `shutdown_job_runner()` then `shutdown_prepare_pool()`.

## Key Files

| File | Responsibility |
|------|---------------|
| `backend/app/resource_detector.py` | `compute_resource_defaults()` -- CPU/RAM detection, formula |
| `backend/app/services/prepare_pool.py` | Global `ThreadPoolExecutor` for image preparation tasks |
| `backend/app/api/dependencies.py` | `acquire_heavy_op` -- admission control semaphore dependency |
| `backend/app/services/job_runner.py` | `JobRunner` class -- background job execution and tracking |
| `backend/app/models/database.py` | `seed_default_settings()` -- persists computed defaults to DB |
| `backend/app/config.py` | `Settings` class -- env-driven configuration |
| `backend/app/main.py` | Lifespan setup -- pool init, semaphore creation, heartbeat |
| `backend/app/process_utils.py` | `get_rss_mb()` -- RSS memory reading via psutil |
| `backend/app/services/app_settings.py` | `AppSettingsService` -- reads concurrency settings from DB |
