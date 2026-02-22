# Ingestion Pipeline

## Overview

The ingestion pipeline processes images from the filesystem into the system: parsing metadata, copying into the object store, generating thumbnails, extracting colors, generating CLIP embeddings, and saving everything to SQLite + Qdrant.

All ingestion runs through **Prefect** flows defined in `backend/flows/ingestion.py`. All flow and task parameters use primitive types (strings, dicts, lists) for JSON serialization compatibility with Prefect deployments.

## Flow Architecture

The pipeline uses a **batched stage architecture** for maximum throughput. Images are processed in configurable batches (default 16) where:
- **Prepare stage** runs concurrently via Prefect `.submit()` (thumbnails + colors per image)
- **CLIP embedding** runs as a batch forward pass (vectorized, 3-5x faster than individual)
- **Database and Qdrant saves** are batched into single transactions

```
Web Upload                              CLI
    │                                    │
    ▼                                    ▼
analyse_upload (deployment)     bulk_image_ingestion (flow)
    │                                    │
    ├── ImageParser.group_files()        │
    ├── generate_preview_thumbnail()     │
    │   (concurrent via .submit())       │
    │                                    │
    ▼                                    │
  [user reviews & edits metadata]        │
    │                                    │
    ▼                                    ▼
process_import_group (deployment)   ┌────────────────────────────┐
    │                               │  Batched Pipeline (per N)  │
    └───────────────────────────────┤                            │
                                    │  1. prepare_single_image   │
                                    │     × N (.submit())        │
                                    │     → parse + copy + dims  │
                                    │     → thumbnails + colors  │
                                    │                            │
                                    │  2. batch_generate_clip    │
                                    │     _embeddings            │
                                    │     (single batch forward  │
                                    │      pass for all N)       │
                                    │                            │
                                    │  3. batch_save_to_database │
                                    │     (single transaction)   │
                                    │                            │
                                    │  4. batch_save_to_qdrant   │
                                    │     (single upsert call)   │
                                    └────────────────────────────┘

process_single_image (thin wrapper for one-off use)
    ├── prepare_single_image (task)
    ├── generate_clip_embedding (task, single image)
    ├── save_to_database (task)
    └── save_to_qdrant (task)
```

## Flows

### `analyse_upload` (Prefect deployment)

Parses and groups uploaded files for the preview UI. Called synchronously by the upload endpoint via `run_deployment(timeout=120)`.

**Parameters:**
- `staging_dir: str` — path to staging directory
- `relative_paths: list[str]` — file paths within staging

**Processing:**
1. Creates an `ImageParser` with tag vocabulary from DB
2. Runs `parser.group_files(relative_paths)` to detect image groups
3. Generates preview thumbnails (120x120 JPEG) concurrently via `.submit()` for each file into `{staging_dir}/.thumbs/`
4. Returns grouped results with per-file metadata and `preview_thumbnail` filenames

**Returns:** `list[dict]` — image groups with parsed metadata (persisted result for cross-process retrieval)

### `process_import_group` (Prefect deployment)

Processes a confirmed image group using the batched pipeline. Called async by the confirm endpoint via `run_deployment(timeout=0)`.

**Parameters:**
- `job_id: str` — ImportJob ID for progress tracking
- `staging_dir: str` — path to staging directory
- `author: str` — user-confirmed author
- `group_name: str` — user-confirmed group name
- `files: list[dict]` — per-file metadata dicts from the confirm request

**Processing:**
1. Filters to existing files upfront
2. For each batch of N images (default 16):
   - Submits `prepare_single_image` concurrently for all images in the batch
   - Runs `batch_generate_clip_embeddings` on all successful preparations
   - Runs `batch_save_to_database` in a single transaction
   - Runs `batch_save_to_qdrant` in a single upsert call
   - Updates `ImportJob` progress after each batch

**Returns:** `dict` with `{job_id, processed, failed, total}`

### `process_single_image` (Prefect flow — thin wrapper)

Processes one image end-to-end. Used for one-off processing; batch flows use the batched pipeline directly.

**Parameters:**
- `image_path: str` — absolute path to the source image
- `source_dir: str | None` — root directory for relative path computation (CLI ingest)
- `metadata: dict | None` — explicit metadata from web import (skips path parsing)

**Pipeline steps:**
1. `prepare_single_image` — parse, copy to store, thumbnails, colors (single task)
2. `generate_clip_embedding` — single-image CLIP inference
3. `save_to_database` — single-image DB save
4. `save_to_qdrant` — single-image Qdrant save

**Returns:** `{"status": "success"|"failed", "image_id": int, "filepath": str}`

### `bulk_image_ingestion` (Prefect flow)

Batch ingestion from one or more source directories (CLI entry point).

1. Builds parser once for all images (avoids per-image DB query)
2. For each source directory, runs `scan_directory` task
3. Processes images in batches using the batched pipeline (same as `process_import_group`)
4. Returns summary: `{total_images, processed, successful, failed, results}`

## Key Tasks

### `prepare_single_image` (Prefect task, retries=2)

The main per-image preparation task. Handles everything except CLIP and saves:

1. **Parse metadata** — CLI mode: `ImageParser.parse()`, Web mode: use explicit dict
2. **Copy to ImageStore** — UUID-based storage key, `image_store.put()`
3. **Get file size** — inline `os.stat()`
4. **Generate thumbnails** — calls `generate_thumbnails.fn()` inline (3 sizes, BILINEAR for small/medium, LANCZOS for large). Also captures image dimensions.
5. **Extract colors** — calls `extract_dominant_colors.fn()` inline (K-means, n_init=3, 5000 pixel sample)

Returns a dict with `image_data`, `original_image_path`, `qdrant_metadata`, and `status`.

### `batch_generate_clip_embeddings` (Prefect task, retries=2)

Processes multiple images through CLIP in a single batch forward pass using `CLIPService.batch_encode_images()`. Sub-batches by `ingestion_batch_size` to manage memory.

### `batch_save_to_database` (Prefect task, retries=2)

Saves multiple images to SQLite in a single session/transaction using shared `_save_image_to_db()` helper.

### `batch_save_to_qdrant` (Prefect task, retries=2)

Saves multiple embeddings to Qdrant in a single `batch_add_embeddings()` call.

## Performance Configuration

Settings in `backend/app/config.py`:

| Setting | Default | Purpose |
|---------|---------|---------|
| `ingestion_batch_size` | 16 | Images per batch for CLIP/DB/Qdrant operations |
| `max_concurrent_prepare` | 8 | Max concurrent `prepare_single_image` tasks |
| `color_kmeans_n_init` | 3 | K-means random initializations |
| `color_clustering_samples` | 5000 | Max pixels sampled for color extraction |

Thumbnail resampling: BILINEAR for 150px and 400px, LANCZOS for 800px. Preview thumbnails use BILINEAR.

## Deployments

Registered via `backend/flows/deploy.py`:

| Deployment Name | Flow | Work Pool | Usage |
|----------------|------|-----------|-------|
| `analyse-deployment` | `analyse_upload` | `battlemap-pool` | Upload endpoint (sync) |
| `import-deployment` | `process_import_group` | `battlemap-pool` | Confirm endpoint (async) |

## CLI Entry Points

- `run_ingestion.py` — runs `bulk_image_ingestion` directly (sets `PREFECT_API_URL` so runs are tracked)
- `backend/flows/deploy.py` — registers deployments with Prefect server

## Prefect Infrastructure

**Docker Compose services (infrastructure only):**
- `prefect-server` — Prefect API + UI at localhost:4200 (Postgres backend)
- `prefect-services` — Background Prefect services (scheduling, etc.)
- `postgres` — Prefect's metadata store
- `redis` — Prefect's messaging/caching layer

**Local process (not Docker):**
- `prefect worker` — runs locally with `uv run prefect worker start --pool battlemap-pool` because it needs access to project code, Python dependencies (CLIP, PIL, etc.), and the local filesystem

**Setup sequence:**
1. `docker compose up -d` — start infrastructure
2. `uv run python -m backend.flows.deploy` — register deployments
3. `uv run prefect worker start --pool battlemap-pool` — start worker
4. Start FastAPI backend

## Staging Cleanup

Staging directories (`data/staging/{job_id}/`) are created on upload and include a `.thumbs/` subdirectory for preview thumbnails. They are currently NOT automatically cleaned up after processing completes. This should be addressed — either:
- Clean up in `process_import_group` after all files are processed
- Add a periodic cleanup job for old staging dirs
- Clean up when the ImportJob transitions to `completed`
