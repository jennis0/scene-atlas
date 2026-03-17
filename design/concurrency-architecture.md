# Concurrency & Resource Architecture

**Last updated**: 2026-03-06

## Guards Overview

| Guard | Mechanism | Default (first boot) | Runtime setting |
|---|---|---|---|
| HTTP admission control | `asyncio.Semaphore` | resource_detector (min 1) | `max_concurrent_heavy_requests` |
| Background job pool | `ThreadPoolExecutor` | resource_detector (min 1) | `max_job_workers` |
| Per-job image prepare | `ThreadPoolExecutor` | resource_detector, RAM-capped | `max_concurrent_prepare` |
| Max file size per upload | request validation | 2 GB | `max_import_file_size` |
| Max video size per upload | request validation | 2 GB | `max_video_file_size` |
| Max files per import | request validation | 1000 | `max_import_files` |
| Max total upload size | request validation | 2 GB | `max_import_total_size` |
| CLIP text cache | LRU cache | 256 entries | `CLIP_TEXT_CACHE_MAX` (env, config.py) |
| Color index TTL | time-based expiry | 60 s | `COLOR_CACHE_TTL_SECONDS` (env, config.py) |
| Job record retention | age-based cleanup | 3600 s | `JOB_RETENTION_SECONDS` (env, config.py) |

All settings require an application restart to take effect.

## Single Source of Truth

**AppSettings DB** is the sole runtime source for all concurrency and import limit settings.
Editable via `PATCH /api/v1/settings`. Takes effect on next restart.

**config.py env vars** are the sole source for service constants (last 3 rows above).
These are low-stakes tuning knobs for operators/developers; no admin UI needed.

## Deployment Modes and Configuration

| Mode | Infrastructure config | AppSettings changes |
|---|---|---|
| Electron app | CLI args + IPC | Admin UI in the app |
| Web server | `.env` file | `PATCH /api/v1/settings` |
| Developer | `.env` file | `PATCH /api/v1/settings` or direct DB |

`.env` is scoped to infrastructure settings only (paths, DB URL, CORS, CLIP model).
It is **never** the mechanism for AppSettings seeding — this ensures all deployment
modes behave identically on first boot.

## First-Boot Seeding

`seed_default_settings()` runs once when the DB is empty (no `.env` involvement):
- Concurrency settings: `resource_detector.compute_resource_defaults()`
- Import limits: sensible hardcoded values (2 GB per file, 1000 files)
- Algorithm params: existing fixed defaults (grid detection, color extraction)

To change any value on an existing deployment: use `PATCH /api/v1/settings` then restart.

## Concurrency: Per-Job Image Prepare

`max_concurrent_prepare` is bounded by **both CPU and memory**.
Each worker holds a decompressed battlemap image in memory (can be hundreds of MB).
OOM crashes occur when this is set too high. Dynamic default:

```python
cpu = os.cpu_count() or 2
ram_gb = psutil.virtual_memory().total / 1024**3
# Reserve ~2 GB: CLIP ~300 MB, LanceDB, Python/uvicorn overhead.
# ~500 MB per prepare worker for large image decode + thumbnails.
available_gb = max(0.5, ram_gb - 2.0)
ram_cap = max(1, int(available_gb / 0.5))
max_concurrent_prepare = max(1, min(cpu, 8, ram_cap))
```

On a 2 GB machine this yields 1 worker — correct and safe.

## Admission Control Semaphore

`asyncio.Semaphore(max_concurrent_heavy_requests)` created in `app.lifespan`, gates
`analyse_staged` and `confirm_all_groups` via `acquire_heavy_op` dependency.

## Memory Monitoring

`process_utils.py:get_rss_mb()` — diagnostic only, logged every 15 s. No hard guard.
`MemoryError` from image processing surfaced via `pipeline/error_classifier.py`.

## Service Constants (env-backed, config.py only)

```
CLIP_TEXT_CACHE_MAX=256       # Max cached text embeddings (LRU); restart to change
COLOR_CACHE_TTL_SECONDS=60    # Color index cache TTL in seconds
JOB_RETENTION_SECONDS=3600    # How long to keep completed job records
```

## Why Not Async SQLAlchemy

`aiosqlite` wraps sync `sqlite3` in a background thread — identical to FastAPI's
threadpool for `def` endpoints. Migration ~400 lines, 103 sites, no practical benefit
on SQLite. Worth revisiting when Postgres is added.

## Key Files

| File | Role |
|---|---|
| `backend/app/resource_detector.py` | CPU/RAM-aware defaults for concurrency settings |
| `backend/app/config.py` | Env-backed infrastructure settings + service constants |
| `backend/app/models/schemas.py` | AppSettings Pydantic model (DB-backed runtime source) |
| `backend/app/models/database.py` | `seed_default_settings()` — resource_detector + hardcoded defaults |
| `backend/app/main.py` | Lifespan: seed → create semaphore from AppSettings DB |
| `backend/app/api/dependencies.py` | `acquire_heavy_op` semaphore dependency |
| `backend/app/services/clip_service.py` | `_TEXT_CACHE_MAX` from `settings.clip_text_cache_max` |
| `backend/app/services/color_search.py` | TTL from `settings.color_cache_ttl_seconds` |
| `backend/app/services/job_runner.py` | Retention from `settings.job_retention_seconds` |
