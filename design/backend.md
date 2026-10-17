# Backend Architecture

## Overview

The backend is a **FastAPI** application serving a REST API for image management, search and import. It uses SQLite (relational data, source of truth), LanceDB (vector embeddings, disk-backed and memory-mapped) and the filesystem (image and thumbnail storage). In-process background work:

- **IngestWorker** — one thread that processes import items (see [ingestion.md](ingestion.md)).
- **JobRunner** — a `ThreadPoolExecutor` for user-triggered maintenance jobs (re-embedding, retagging, backfills, model downloads, library deletion).
- **Scheduler** — asyncio-driven periodic maintenance.

Concurrency limits are described in [resource-management.md](resource-management.md).

## Directory Structure

```
backend/
├── app/
│   ├── api/                      # Route handlers (one router per module)
│   │   ├── dependencies.py       # get_db, acquire_heavy_op (admission semaphore)
│   │   ├── export.py             # Library ZIP export
│   │   ├── groups.py             # Group detail, edit, merge, move, ZIP download, picker search
│   │   ├── images.py             # Image CRUD + file/thumbnail serving
│   │   ├── imports.py            # Import jobs: manifest, archives, seal, content upload, actions
│   │   ├── jobs.py               # Background job status
│   │   ├── models.py             # Embedding model list/download/switch
│   │   ├── rate_limits.py        # Shared slowapi Limiter
│   │   ├── search.py             # Image and group search, facets
│   │   ├── settings.py           # DB-backed app settings
│   │   ├── system.py             # Library info, delete library, reset tags
│   │   └── tags.py               # Tag categories, values, packs
│   ├── data/
│   │   ├── tag_vocabulary.json   # Canonical tag vocabulary + genre packs
│   │   └── vocabulary.py         # Vocabulary loader
│   ├── models/
│   │   ├── database.py           # SQLAlchemy models, engine, init_db (Alembic), seeding
│   │   ├── import_schemas.py     # Pydantic models for the imports API
│   │   └── schemas.py            # Pydantic models for all other APIs, AppSettings
│   ├── services/
│   │   ├── app_settings.py       # Read/write app_settings rows
│   │   ├── clip_service.py       # ONNX embedding models (CLIP / SigLIP2)
│   │   ├── color_search.py       # Colour proximity search (HSL cylinder distance)
│   │   ├── deletion_service.py   # Image deletion with ref-counted file cleanup
│   │   ├── fts_service.py        # SQLite FTS5 helpers, alias expansion
│   │   ├── grid_detector.py      # Image-based grid detection
│   │   ├── image_parser.py       # Filename/path metadata parser
│   │   ├── image_store.py        # Hash-sharded filesystem store
│   │   ├── ingest_state.py       # Import item/job state machines (pure)
│   │   ├── job_runner.py         # JobRunner (ThreadPoolExecutor + status tracking)
│   │   ├── lancedb_service.py    # LanceDB client
│   │   ├── memory_budget.py      # MemoryBudget for image preparation
│   │   ├── model_download_service.py  # HuggingFace model downloads
│   │   ├── model_registry.py     # Static registry of embedding models
│   │   ├── ort_providers.py      # ONNX Runtime provider selection + GPU fallback
│   │   ├── prepare_pool.py       # Shared prepare ThreadPoolExecutor
│   │   ├── scheduler.py          # Periodic task scheduler
│   │   ├── search_service.py     # Hybrid search, filters, facets (see search.md)
│   │   ├── tag_packs.py          # Tag pack import
│   │   ├── validation.py         # ZIP safety check, MIME verification
│   │   └── video_utils.py        # Video first frame + dimensions
│   ├── config.py                 # Pydantic settings (env-driven)
│   ├── logging_config.py         # Console + rotating file logging; Pillow pixel limit
│   ├── main.py                   # App creation, middleware, routers, lifespan
│   ├── process_utils.py          # RSS reading
│   └── resource_detector.py      # CPU/RAM-based concurrency defaults
├── pipeline/
│   ├── ingest_queue.py           # Durable item/job operations (create, manifest, plan, claim, actions)
│   ├── ingest_archive.py         # ZIP expansion into import items
│   ├── ingest_process.py         # Batch processing: prepare → embed → commit → vectors
│   ├── ingest_worker.py          # IngestWorker thread
│   ├── ingest_maintenance.py     # Scheduled ingest cleanup (state-driven)
│   ├── image_hashes.py           # SHA-256, pixel hash, perceptual hash
│   ├── vector_reconcile.py       # Align LanceDB with SQLite by image id
│   ├── maintenance.py            # Backups + orphaned store file sweep
│   ├── error_classifier.py       # Exception → user-facing error kind/reason
│   ├── pipeline_config.py        # PipelineConfig built from app settings
│   ├── naming.py                 # Filename/export path helpers
│   ├── export_library.py         # Export library to a directory tree
│   ├── write_new_embeddings.py   # Re-embed all images (background job)
│   ├── retag_all_images.py       # Retag job
│   ├── backfill_grid_detection.py # Grid detection backfill job
│   ├── backfill_content_hash.py  # content_hash backfill utility
│   ├── fix_orphaned_images.py    # Assign groupless images utility
│   ├── reparse_names.py          # Re-run name parsing utility
│   ├── db.py                     # Session helper for pipeline scripts
│   └── tasks/
│       ├── color_extraction.py   # K-means dominant colours
│       ├── embedding_generation.py # Embedding generation
│       ├── grid_detection.py     # Grid detection wrapper
│       └── image_processing.py   # Thumbnail generation
├── alembic/versions/             # Database migrations
├── pyinstaller/                  # Frozen sidecar entry point + spec
├── scripts/                      # Developer scripts (grid detection eval)
└── tests/                        # unit/, integration/, fixtures/
```

## API Endpoints

All API routes are mounted under `/api/v1` (`settings.api_prefix`); router prefixes are set in `main.py`. `/health` and `/` are at the root.

### Images (`/images`)
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | List images |
| GET | `/authors` | Distinct author values |
| GET | `/{id}` | Get one image |
| PATCH | `/{id}` | Update image metadata |
| DELETE | `/{id}` | Delete image and its files |
| GET | `/{id}/scenes` | Other images in the same group |
| GET | `/{id}/file` | Serve the original file |
| GET | `/{id}/thumbnail` | Serve a thumbnail (falls back to the original) |
| POST | `/backfill-grids` | Grid detection backfill job (rate limited: expensive) |

### Search (`/search`)
Logic lives in `backend/app/services/search_service.py`; ranking is described in [search.md](search.md).

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | Image search → `ImageSearchResponse` (`total`, `limit`, `offset`, `images`, `scores`) |
| GET | `/groups` | Group search → `GroupSearchResponse` (`total_groups`, `limit`, `offset`, `groups`) |
| GET | `/facets` | Filter panel option counts |
| POST | `/rebuild-embeddings` | Re-embed all images job (rate limited: expensive) |

Shared parameters for `/` and `/groups`:
- `query`, `semantic_only`, `text_only` — the frontend maps a `~` prefix to `semantic_only` and `=` to `text_only`.
- Filters: `tags`, `exclude_tags`, `authors`, `exclude_authors`, `colors`, `image_types`, `media_types`, `gridded`, `gridded_unknown`, `grid_type`. Tags are OR within a category and AND across categories; colours are OR.
- `sort_by` (`created_at` | `name` | `relevance`, default `created_at`), `sort_dir` (`asc` | `desc`), `limit`, `offset`.

`/groups` also takes `include_all_image_ids` (populate `all_image_ids`, used by Edit All). Without a query, groups are listed in `sort_by` order; with a query, groups are ranked by their best-matching image and `sort_by` is ignored. Each `GroupSearchResult` has `group_id`, `base_name`, `author`, `hero_image`, `mosaic_images`, `total_scenes`, `matching_scenes`, `best_score`, `all_image_ids`. `limit` defaults to 50 (max 500) for groups and 500 (max 2000) for images.

### Groups (`/groups`)
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/search` | Typeahead group picker (`q`, `exclude_id`, `reference_name`) |
| GET | `/{id}` | Group with members |
| GET | `/{id}/download` | Stream group as ZIP |
| PUT | `/{id}` | Update group metadata |
| DELETE | `/{id}` | Delete group |
| POST | `/{id}/move-images` | Move images between groups |
| POST | `/{id}/merge` | Merge this group into a target group |

### Tags (`/tags`)
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/categories` | List categories |
| POST | `/categories` | Create category |
| GET | `/categories/{name}` | Get category |
| PATCH | `/categories/{name}` | Update category (cascade renames) |
| DELETE | `/categories/{name}` | Delete category (cascade deletes) |
| PUT | `/categories/{name}/tags/{value}` | Add/update tag value + aliases |
| PATCH | `/categories/{name}/tags/{value}` | Rename tag value |
| DELETE | `/categories/{name}/tags/{value}` | Delete tag value |
| GET | `/values/{category}` | Values for a category |
| GET | `/image/{id}` | Tags for an image |
| POST | `/image/{id}` | Add tag to an image |
| DELETE | `/{tag_id}` | Remove a tag |
| GET | `/stats` | Tag statistics |
| GET | `/packs` | Tag packs with import status |
| POST | `/packs/import-multiple` | Import several packs (setup wizard) |
| POST | `/packs/{name}/import` | Import one pack (rate limited: expensive) |
| POST | `/retag-all` | Retag job (rate limited: expensive) |

### Imports (`/imports`)
Defined in `backend/app/api/imports.py`. The flow and state machines are in [ingestion.md](ingestion.md).

| Method | Path | Purpose |
|--------|------|---------|
| GET | `` | Job summaries + queue status (ETag / `If-None-Match`) |
| POST | `` | Create an import job |
| POST | `/queue/probe` | Re-check system pause conditions now |
| GET | `/{job_id}` | Job detail |
| GET | `/{job_id}/items` | Paginated items (filter by state, group, error kind) |
| POST | `/{job_id}/manifest` | Add a chunk of file descriptions (no bytes); unsealed jobs only |
| PUT | `/{job_id}/archives` | Upload a ZIP (raw body); expanded into items; unsealed jobs only. Holds the heavy-op semaphore |
| POST | `/{job_id}/seal` | Close the file list, plan groups, start processing. Idempotent. Holds the heavy-op semaphore |
| POST | `/{job_id}/hashes` | Client SHA-256s; known files become duplicates without upload |
| PUT | `/{job_id}/items/{item_id}/content` | Upload one file's bytes (raw body). Idempotent |
| POST | `/{job_id}/pause` | Pause |
| POST | `/{job_id}/resume` | Resume |
| POST | `/{job_id}/cancel` | Stop; finished files are kept |
| POST | `/{job_id}/retry` | Retry failed items (all or `item_ids`) |
| POST | `/{job_id}/import-as-copy` | Import duplicates as independent images |
| POST | `/{job_id}/finish-upload` | Skip items whose bytes never arrived |
| POST | `/{job_id}/groups/{group_id}/skip` | Skip a planned group |
| POST | `/{job_id}/dismiss` | Hide a finished job from the activity dock |
| DELETE | `/{job_id}` | Undo: delete the images this import created, then the job |

### Jobs (`/jobs`)
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | List JobRunner jobs |
| GET | `/{id}` | JobRunner job status |

### Export (`/export`)
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/library` | Stream library as ZIP (rate limited: expensive) |

### System (`/system`)
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/info` | Storage usage and library stats |
| DELETE | `/library` | Delete entire library job (rate limited: destructive) |
| POST | `/tags/reset` | Reset tags to seed defaults (rate limited: destructive) |

### Settings (`/settings`)
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | Get app settings |
| PATCH | `/` | Update app settings (rate limited: expensive) |

### Models (`/models`)
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | Models with download status |
| GET | `/embedding-status` | Embedding service loading status |
| GET | `/setup-status` | First-run setup status (GPU detection, recommended model) |
| POST | `/{name}/download` | Download a model without activating it |
| GET | `/{name}/embeddings` | LanceDB stats for a model's table |
| DELETE | `/{name}/embeddings` | Delete a model's embeddings |
| POST | `/active` | Set active model (download + re-embed job) |
| POST | `/setup-complete` | Mark first-run setup done |

### Root
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | Deep health check: database, LanceDB, embedding model, JobRunner |
| GET | `/` | SPA `index.html` when a frontend build exists; otherwise a status page (server mode) or JSON |

When `frontend/dist` exists, `/assets` is served statically and a catch-all route serves `index.html` for client-side routes.

## Services

### ImageStore
Hash-sharded object store: `put(key, path)`, `put_bytes(key, data)`, `get_path(key)`, `exists(key)`, `delete(key)`. Two instances: images (library root) and thumbnails. See [storage.md](storage.md).

### CLIPService
Embedding service for CLIP ViT-B/32, SigLIP2-base and SigLIP2-so400m via ONNX Runtime. Loaded in a background thread at startup. `encode_image(path)`, `encode_text(query)` (LRU-cached), `batch_encode_images(paths)`.

### Model registry and downloads
`model_registry.py` is the static registry of model specs (names, HF repos, hardware recommendations). `model_download_service.py` downloads to `APP_DATA_DIR/models/{name}/` via temp-dir → rename; `version.json` marks completion.

### LanceDBService
Disk-backed LanceDB client managing `embeddings_{model_name}` tables. A `threading.RLock` serialises write operations. `add_image_embedding`, `batch_add_embeddings`, `search_similar`, `delete_image_embedding`, `delete_embeddings`, `get_all_ids`.

### ImageParser
Filename/path parser with DB-driven tag vocabulary. See [parser.md](parser.md).

### FTS service
SQLite FTS5 over `image_fts` (Porter stemmer), BM25 ranking, query sanitisation and tag alias expansion.

### Colour search
Colour proximity using distance in an HSL cylinder, with an in-memory index cached for `color_cache_ttl_seconds`.

### Ingest state (`ingest_state.py`)
Pure transition tables for item states (`awaiting_bytes`, `ready`, `processing`, `done`, `duplicate`, `failed`, `skipped`) and job states (`active`, `paused`, `completed`, `cancelled`). All item updates go through it.

### IngestWorker (`backend/pipeline/ingest_worker.py`)
One daemon thread per process. Sleeps until woken (bytes received, seal, resume, retry) or a 30 s timeout, claims a batch of up to `ingestion_batch_size` ready items round-robin across jobs, and processes it with `process_batch` (prepare on the prepare pool → embed → one `BEGIN IMMEDIATE` commit → LanceDB write → staging cleanup). When the system is unfit (model unavailable, library folder missing, < 512 MB free on an ingest volume) it stops claiming and re-probes instead of failing items. `recover()` clears `.incoming/` temp files and re-queues items left `processing` by a dead process; `stop()` lets the in-flight batch finish. `drain()` runs synchronously for tests.

### MemoryBudget (`backend/app/services/memory_budget.py`)
Process-wide byte budget. Each prepare step reserves its estimated peak decode memory before decoding and blocks while the budget is exhausted; an item larger than the whole budget runs alone. Capacity is `ingest_memory_budget_mb` or half of RAM beyond a 2 GiB reserve (minimum 1 GiB).

### PreparePool
Shared `ThreadPoolExecutor` (`max_concurrent_prepare` workers) for per-image preparation: hashing, decode, thumbnails, colours, grid detection.

### DeletionService
`safe_delete_image` deletes the row and, if no other row references the same `storage_key`, the stored file and thumbnails, plus the vector. `delete_image_rows` does the same for many images and returns the file deletions to apply after commit.

### Validation
`check_zip_safety` (entry count, uncompressed size, zip-slip) and `verify_media_mime` (file header matches extension).

### VideoUtils
First-frame extraction and dimension reading for videos.

### AppSettingsService
Reads/writes the `app_settings` table (runtime tuning, feature flags, import limits). Seeded on first boot by `seed_default_settings()`.

### JobRunner
`ThreadPoolExecutor` (`max_job_workers`, created eagerly in the lifespan) with in-memory job status, progress and results. Used for embedding rebuild/reconcile, retagging, grid backfill, model download/activation and library deletion. Not used for imports.

### Scheduler
Asyncio scheduler; each task runs in the default executor. Last successful run times are persisted under `APP_DATA_DIR/scheduler`, so overdue tasks run 60 s after startup. Registered when `scheduler_enabled`:

| Task | Interval | Function |
|------|----------|----------|
| `backup_database` | 24 h | `pipeline/maintenance.py` |
| `ingest_maintenance` | 6 h | `pipeline/ingest_maintenance.py:run_ingest_maintenance` |
| `sweep_orphaned_store_files` | 24 h | `pipeline/maintenance.py` |
| `reconcile_vectors` | 24 h | `pipeline/vector_reconcile.py` |

## Configuration

Two sources:

- **`backend/app/config.py`** (`pydantic-settings`, env vars or `.env`, case-insensitive) — infrastructure and service constants.
- **`app_settings` table** — runtime tuning (concurrency, import limits, algorithm parameters), edited via `PATCH /api/v1/settings`. See [resource-management.md](resource-management.md).

`config.py` keys:

| Key | Default | Notes |
|-----|---------|-------|
| `app_mode` | `server` | `app` when run as the Electron sidecar |
| `debug` | `False` | Debug logging; uvicorn reload when run via `main.py` |
| `app_data_dir` | `<repo>/data` | Fast storage root |
| `image_library_dir` | `<repo>/images` | Originals + backups root |
| `validate_roots` | `False` | Fail startup if roots are missing (frozen entry point) |
| `database_url` | computed | Always `sqlite:///{app_data_dir}/battlemap.db` |
| `store_thumbnails_dir`, `staging_dir`, `vector_db_path`, `config_dir`, `store_images_dir`, `backups_dir` | computed | Derived from the two roots in `__init__` |
| `vector_size` | `512` | Overwritten at startup from the model manifest's `embedding_dim` |
| `embedding_model` | `clip-vit-b-32` | Used for `vector_collection_name` |
| `inference_device` | `auto` | `auto` / `cpu` / `cuda` / `directml` / `coreml` |
| `clip_text_cache_max` | `256` | Text embedding LRU size |
| `color_cache_ttl_seconds` | `60.0` | Colour index cache TTL |
| `job_retention_seconds` | `3600` | How long finished JobRunner records are kept |
| `thumbnail_sizes` | `[(150,150), (400,400), (800,800)]` | small / medium / large |
| `max_image_size` | `10 MiB` | Not referenced outside `config.py` |
| `max_image_pixels` | `1_000_000_000` | Pillow `MAX_IMAGE_PIXELS`; above it decoding fails as a decompression bomb |
| `pixel_hash_max_pixels` | `100_000_000` | JPEGs above this are decoded at reduced scale and skip the pixel hash |
| `ingest_memory_budget_mb` | `None` | MemoryBudget capacity; `None` = automatic |
| `max_import_items` | `50_000` | Max files per import job, across all manifest chunks |
| `ingest_worker_enabled` | `True` | Start the IngestWorker at startup (tests disable it) |
| `supported_formats` | `.jpg .jpeg .png .webp` | Image extensions |
| `supported_video_formats` | `.mp4 .webm` | Video extensions |
| `rate_limit_expensive` | `2/minute` | |
| `rate_limit_destructive` | `1/minute` | |
| `rate_limit_enabled` | `True` | |
| `api_host` / `api_port` / `api_prefix` | `0.0.0.0` / `8000` / `/api/v1` | |
| `cors_origins` | `localhost:3000`, `:5173`, `:8000` | Startup warning if unchanged in server mode |

Other environment variables: `EMBEDDING_MODEL` (operator override of the active model, read by `clip_service.py`; otherwise `app_settings.active_model`), `CONVERT_TO_WEBP` (initial value of the `convert_to_webp` setting at first boot).

## Startup Sequence (`main.py` lifespan)

1. `setup_logging()` — console + rotating file handlers; sets Pillow's pixel limit to `max_image_pixels` and turns `DecompressionBombWarning` into an error.
2. `get_engine()` + `init_db()` — runs Alembic migrations (stamps pre-Alembic databases at head).
3. `seed_tag_categories()`, `seed_default_settings()` (first boot only), `backfill_search_text()`, then read app settings.
4. `init_prepare_pool(max_concurrent_prepare)`; store engine on `app.state.db_engine`; create `app.state.heavy_op_semaphore`.
5. Set `settings.vector_size` from the model manifest.
6. Start the embedding model background load.
7. Create the JobRunner. A daemon thread waits for the model, calls `IngestWorker.probe_now()`, then submits `reconcile_vectors` if the model loaded.
8. If `ingest_worker_enabled`: `ingest_worker.recover()`, then `ingest_worker.start()`.
9. If `scheduler_enabled`: register the four scheduler tasks and start the scheduler.
10. Log the CORS warning if applicable; print `SCENE_ATLAS_READY port=…` (Electron waits for this line).
11. Start the 15 s event-loop heartbeat (logs thread count and RSS); install a SIGUSR1 thread-dump handler on non-Windows.

Shutdown: cancel heartbeat → stop scheduler → `ingest_worker.stop(60s)` → `shutdown_job_runner()` → `shutdown_prepare_pool()` → `shutdown_lancedb_service()`.

## Middleware

CORS (`cors_origins`), `SecurityHeadersMiddleware` (pure ASGI) and `SlowAPIMiddleware`. A global exception handler logs unhandled exceptions and returns a generic 500. See [security.md](security.md).

## Dependencies Between Services

```
API endpoints
  ├── SQLAlchemy session (Depends(get_db); imports use BEGIN IMMEDIATE write sessions)
  ├── ImageStore / ThumbnailStore (file serving)
  ├── search_service → FTS, CLIPService, LanceDBService
  ├── ingest_queue (imports API) → wakes IngestWorker
  └── JobRunner (maintenance jobs)

IngestWorker
  ├── ingest_queue (claim, record results)
  ├── PreparePool + MemoryBudget (prepare)
  ├── CLIPService (embed batch)
  ├── ImageStore / ThumbnailStore (atomic placement from .incoming/)
  └── LanceDBService (vectors after commit; vector_reconcile repairs gaps)
```
