# Backend Architecture

## Overview

The backend is a **FastAPI** application serving a REST API for image management, search, and import. It connects to SQLite (relational data), Qdrant embedded (vector embeddings), and the filesystem (image/thumbnail storage). Background work runs in-process via a `JobRunner` (ThreadPoolExecutor) and periodic maintenance via a `Scheduler` (asyncio).

## Directory Structure

```
backend/
├── app/
│   ├── api/              # API route handlers
│   │   ├── groups.py     # Image group CRUD, merge, mass-edit
│   │   ├── images.py     # CRUD + file serving for images
│   │   ├── imports.py    # Web import upload/confirm/status
│   │   ├── jobs.py       # Background job status API
│   │   ├── search.py     # Text, filter, and semantic search
│   │   └── tags.py       # Tag categories and tag CRUD
│   ├── models/
│   │   ├── database.py   # SQLAlchemy models + DB setup + seed data
│   │   └── schemas.py    # Pydantic request/response schemas
│   ├── services/
│   │   ├── clip_service.py      # CLIP model for embeddings
│   │   ├── color_search.py      # Color-based image search (LAB distance)
│   │   ├── ort_providers.py     # ONNX Runtime provider resolution + GPU fallback
│   │   ├── deletion_service.py  # Cascade deletion (image + store + Qdrant)
│   │   ├── fts_service.py       # SQLite FTS5 full-text search
│   │   ├── grid_detector.py     # Image-based grid detection algorithm
│   │   ├── image_parser.py      # Filename/path metadata parser
│   │   ├── image_store.py       # Hash-sharded filesystem storage
│   │   ├── job_runner.py        # Background job runner (ThreadPoolExecutor)
│   │   ├── qdrant_service.py    # Qdrant embedded vector DB client
│   │   ├── scheduler.py         # Periodic task scheduler (asyncio)
│   │   ├── validation.py        # Input validation helpers
│   │   └── video_utils.py       # Video frame extraction + dimensions
│   ├── config.py         # Pydantic settings (env-driven)
│   └── main.py           # FastAPI app creation, router mounting, startup
├── pipeline/
│   ├── ingestion.py              # Image ingestion (analyse, process, bulk ingest)
│   ├── maintenance.py            # Backup + staging cleanup (scheduled)
│   ├── logger.py                 # Logging helper for pipeline modules
│   ├── backfill_content_hash.py  # Hash backfill CLI utility
│   ├── backfill_grid_detection.py # Grid detection backfill CLI utility
│   ├── fix_orphaned_images.py    # Orphaned image repair CLI utility
│   ├── reparse_names.py          # Name reparsing CLI utility
│   ├── retag_all_images.py       # Retagging CLI utility
│   ├── write_new_embeddings.py   # Embedding regeneration (background job)
│   └── tasks/
│       ├── color_extraction.py      # K-means dominant color extraction
│       ├── embedding_generation.py  # CLIP embedding generation
│       ├── grid_detection.py        # Image-based grid analysis
│       └── image_processing.py      # Thumbnails, dimensions, file size
├── alembic/              # Database migrations
└── tests/
```

## API Endpoints

All endpoints are prefixed with `/api/v1`.

### Images (`/images`)
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | List images (paginated) |
| GET | `/authors` | List distinct author values |
| GET | `/{id}` | Get single image |
| PATCH | `/{id}` | Update image metadata (name, subgroup, grid info, type) |
| DELETE | `/{id}` | Delete image + files |
| GET | `/{id}/scenes` | Get group members (scenes) |
| GET | `/{id}/file` | Serve original image file |
| GET | `/{id}/thumbnail` | Serve thumbnail (falls back to original) |
| POST | `/backfill-grids` | Trigger grid detection backfill (background job) |

### Search (`/search`)
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | Multi-faceted search (text + tags + colors + semantic), returns flat Image[] |
| GET | `/groups` | **[NEW]** Grouped search — returns groups with pagination, image IDs, and scores. See below. |
| GET | `/facets` | Filter panel facet counts |
| POST | `/rebuild-embeddings` | Trigger CLIP embedding rebuild (background job) |

**GET `/groups` — Grouped Search Endpoint**

Returns `GroupSearchResponse` with paginated groups. Supports two modes:

**Browse Mode (no query):**
- Groups sorted alphabetically by `baseName`
- All groups returned; image IDs included for all images in each group
- Used for initial gallery view

**Search Mode (query parameter):**
- Groups sorted by `bestScore` descending (semantic or RRF score)
- Returns only groups with matching images
- Image IDs in `all_image_ids` are only matching images (non-matching group members excluded)
- Non-matching group members marked as `outOfScope` in Edit All dialogs

**Parameters:**
- `query?: string` — text or semantic search string
- `authors?: string[]` — filter by author (OR semantics)
- `tags?: string[]` — filter by tags (OR within category, AND across)
- `colors?: string[]` — filter by dominant color (OR)
- `gridded?: 'true' | 'false' | 'unknown'` — filter by grid state
- `image_type?: 'battlemap' | 'scene'` — filter by image type
- `media_type?: 'image' | 'video'` — filter by media type
- `min_score?: number` — relevance slider threshold (0.0-1.0)
- `semantic_only?: boolean` — restrict to semantic search only (no text/FTS)
- `text_only?: boolean` — restrict to text/FTS search only (no semantic)
- `sort_by?: string` — sort field (e.g. `baseName`, `bestScore`)
- `sort_dir?: string` — sort direction (`asc` or `desc`)
- `limit?: number` — groups per page (default 50, max 500)
- `offset?: number` — pagination offset
- `include_all_image_ids?: boolean` — populate `all_image_ids` field (default false). Used by Edit All to fetch all in-scope image IDs.

**Response (`GroupSearchResponse`):**
```json
{
  "groups": [
    {
      "group_id": 123,
      "base_name": "Forest Variants",
      "author": "Czepeku",
      "hero_image": { /* full Image object */ },
      "mosaic_images": [ /* 3-4 full Image objects */ ],
      "total_scenes": 45,
      "matching_scenes": 12,
      "best_score": 0.876,
      "all_image_ids": [1, 2, 3, ...] // only present when include_all_image_ids=true
    }
  ],
  "total_groups": 127,
  "page": 0,
  "limit": 50
}
```

### Groups (`/groups`)
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/{id}` | Get group with members |
| GET | `/{id}/download` | Stream group as ZIP archive |
| PUT | `/{id}` | Update group metadata |
| DELETE | `/{id}` | Delete group |
| POST | `/{id}/move-images` | Move images between groups |
| POST | `/{id}/merge` | Merge another group into this one |

### Tags (`/tags`)
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/categories` | List tag categories |
| POST | `/categories` | Create new category |
| GET | `/categories/{name}` | Get specific category |
| PATCH | `/categories/{name}` | Update category (cascade renames) |
| DELETE | `/categories/{name}` | Delete category (cascade deletes) |
| PUT | `/categories/{name}/tags/{value}` | Add/update tag value + aliases |
| PATCH | `/categories/{name}/tags/{value}` | Rename a tag value |
| DELETE | `/categories/{name}/tags/{value}` | Delete a tag value |
| GET | `/values/{category}` | List values for a category |
| GET | `/image/{id}` | List tags for an image |
| POST | `/image/{id}` | Add tag to image |
| DELETE | `/{tag_id}` | Remove a tag |
| GET | `/stats` | Tag statistics |
| POST | `/retag-all` | Trigger full retag job |

### Imports (`/imports`)
| Method | Path | Purpose |
|--------|------|---------|
| POST | `/check-hashes` | Pre-flight duplicate check via content hash |
| POST | `/init` | Initialise a new import job |
| POST | `/upload` | Upload files for import analysis |
| POST | `/{job_id}/confirm-all` | Confirm all groups at once |
| GET | `/{job_id}/status` | Check import job progress |
| GET | `/{job_id}/analysis` | Get or reconnect to analysis results |
| POST | `/{job_id}/cancel` | Cancel an import job |
| POST | `/{job_id}/groups/{gid}/cancel` | Cancel a single group |
| GET | `/{job_id}/preview/{path}` | Serve preview thumbnail |
| GET | `/active` | List active import jobs |
| POST | `/{job_id}/upload-batch` | Batch file upload for import job |
| POST | `/{job_id}/analyse` | Trigger group detection on uploaded files |
| POST | `/{job_id}/report-skipped` | Report skipped files from client |
| POST | `/{job_id}/fail` | Client failure reporting (marks job as failed) |
| DELETE | `/cleanup` | Clean up old/expired imports |

### Jobs (`/jobs`)
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | List background jobs |
| GET | `/{id}` | Get background job status |

### Export (`/export`)
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/library` | Stream entire library as ZIP |

### System (`/system`)
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/info` | Storage usage and library stats |
| DELETE | `/library` | Delete entire library (background job) |
| POST | `/tags/reset` | Reset tags to seed defaults |

### Settings (`/settings`)
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | Get app settings |
| PATCH | `/` | Update app settings |

### Models (`/models`)
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/setup-status` | First-time setup status (GPU detection, recommended model) |
| GET | `/` | List available models with download status |
| POST | `/active` | Set active embedding model (triggers download + re-embed job) |
| POST | `/{name}/download` | Download a model without activating it |
| DELETE | `/{name}/embeddings` | Delete a model's stale embeddings |
| GET | `/embedding-status` | CLIP service loading status |
| POST | `/setup-complete` | Mark first-time setup done |

### Health
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | Deep health check (DB + Qdrant + job runner) |

## Services

### ImageStore
Hash-sharded object store. Interface: `put(key, path)`, `get_path(key)`, `delete(key)`, `exists(key)`. Two instances: one for images, one for thumbnails. See [storage.md](storage.md).

### CLIPService
Multi-model embedding service (CLIP ViT-B/32, SigLIP2-base, SigLIP2-so400m) via ONNX Runtime. Lazy-loaded on first use. Methods: `encode_image(path) -> [float]`, `encode_text(query) -> [float]`, `batch_encode_images(paths)`.

### ModelRegistryService
Module (not a class): `backend/app/services/model_registry.py` — Static registry of all three ONNX model specs (names, HF repos, descriptions, hardware recommendations). Single source of truth used by the download service, API, and export/publish scripts.

### ModelDownloadService
`backend/app/services/model_download_service.py` — Downloads models from HuggingFace to `APP_DATA_DIR/models/{name}/` using atomic temp-dir→rename pattern. `version.json` is the completion marker. Exposes `is_model_downloaded()`, `get_version_info()`, `download_model()`, `get_all_model_statuses()`.

### QdrantService
Embedded Qdrant vector DB client (local mode, no Docker). Manages the `battlemap_images` collection. Thread-safe via `threading.RLock`. Methods: `add_image_embedding`, `search_similar`, `delete_image_embedding`, `batch_add_embeddings`.

### ImageParser
Filename/path parser with DB-driven tag vocabulary. See [parser.md](parser.md).

### FTSService
SQLite FTS5 full-text search. Manages the `image_fts` virtual table with Porter stemmer. Provides `search(query) -> [(image_id, rank)]` for BM25-ranked text search.

### ColorSearch
Color-based image search using CIE LAB distance. Finds images with dominant colors near a given hex color within a configurable threshold.

### ImportStateService
State machine for import job lifecycle. Validates transitions between the 7 import statuses (uploading → staging → active → completed/failed/cancelled/expired). See [import-state-machine.md](import-state-machine.md).

### DeletionService
Cascade deletion of images — removes DB records, ImageStore files, thumbnails, and Qdrant embeddings in a single transaction.

### ValidationService
Input validation helpers (file size, file type, path traversal prevention).

### VideoUtils
Video frame extraction and dimension reading for video media type support.

### AppSettingsService
Manages the `app_settings` database table for runtime-configurable feature flags and tuning parameters (grid detection, color extraction, concurrency limits). Settings are seeded at first boot via `seed_default_settings()`. See `backend/app/services/app_settings.py`.

### StagingService
Manages temporary files during imports. Handles UUID-based flat-file storage with `.file_map.json` sidecar for path mapping. See `backend/app/services/staging.py`.

### PreparePoolService
Global `ThreadPoolExecutor` for CPU-heavy image preparation tasks (thumbnails, colors, grid detection). Capped by `max_concurrent_prepare` to prevent OOM. See `backend/app/services/prepare_pool.py`.

### JobRunner
In-process background job runner using `ThreadPoolExecutor` (default 2 workers). Tracks job status, progress, and results in memory. Jobs are submitted from API endpoints and execute pipeline functions.

### Scheduler
Lightweight asyncio-based periodic task scheduler. Registers maintenance tasks during FastAPI lifespan startup:
- `backup_database` — every 24h
- `cleanup_staging` — every 6h
- `expire_stale_jobs` — every 6h
- `sweep_orphaned_store_files` — every 24h
- `check_qdrant_sync` — every 24h

## Configuration

All config via `backend/app/config.py` using `pydantic-settings`. Reads from `.env` file. Key settings:

- `database_url` — SQLite path (default: `sqlite:///./data/battlemap.db`)
- `store_images_dir` / `store_thumbnails_dir` — object store base directories
- `staging_dir` — temp directory for import uploads
- `qdrant_path` — Qdrant embedded local storage directory
- `EMBEDDING_MODEL` env var — operator override for active model name (`small`/`medium`/`large`); bypasses DB setting entirely
- Active model otherwise resolved from DB `app_settings.active_model` key (set via `POST /api/v1/models/active`)
- `inference_device` — ONNX Runtime execution provider (`auto`/`cpu`/`cuda`/`directml`/`coreml`)
- `max_job_workers` — concurrent background job threads (runtime setting, DB-backed via `AppSettings`, not an env var)
- `scheduler_enabled` — periodic maintenance (runtime setting, DB-backed via `AppSettings`, not an env var)
- `cors_origins` — allowed origins (localhost:3000, localhost:5173)

## Startup Sequence

1. FastAPI app created in `main.py`
2. On startup: create DB engine, run `init_db()` (create tables), run `seed_tag_categories()` (upsert vocabulary)
3. Run `cleanup_stale_staging()` and `mark_interrupted_jobs()` to recover from unclean shutdowns
4. Begin CLIP model background load (non-blocking, loads in a background thread)
4b. If no model is present in APP_DATA_DIR, CLIPService enters an error state; frontend shows ModelSetupScreen overlay (web mode) blocking access until a model is downloaded.
5. Start JobRunner (background thread pool), start Scheduler (periodic tasks)
6. Start event loop heartbeat diagnostics (monitors asyncio event loop health)
7. Store DB engine in `app.state.db_engine` for dependency injection
8. Routes mounted with `/api/v1` prefix

## Dependencies Between Services

```
API endpoints
  ├── SQLAlchemy (db session via Depends)
  ├── ImageStore / ThumbnailStore (file serving)
  ├── CLIPService (semantic search)
  └── QdrantService (embedded vector search, thread-safe via RLock)

Background jobs (via JobRunner)
  ├── SQLAlchemy (save_to_database)
  ├── ImageStore (copy files into store)
  ├── ImageParser (metadata extraction)
  ├── CLIPService (embedding generation)
  └── QdrantService (save embeddings)
```
