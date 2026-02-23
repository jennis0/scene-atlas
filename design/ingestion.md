# Ingestion Pipeline

## Overview

The ingestion pipeline processes images from the filesystem into the system: parsing metadata, copying into the object store, generating thumbnails, extracting colors, generating CLIP embeddings, and saving everything to SQLite + Qdrant.

All ingestion runs through functions defined in `backend/pipeline/ingestion.py`. Background execution is handled by the in-process `JobRunner` (ThreadPoolExecutor).

## Pipeline Architecture

The pipeline uses a **batched stage architecture** for maximum throughput. Images are processed in configurable batches (default 16) where:
- **Prepare stage** runs concurrently via `ThreadPoolExecutor` (thumbnails + colors per image)
- **CLIP embedding** runs as a batch forward pass (vectorized, 3-5x faster than individual)
- **Database and Qdrant saves** are batched into single transactions

```
Web Upload                              CLI
    │                                    │
    ▼                                    ▼
analyse_upload                  bulk_image_ingestion
    │                                    │
    ├── ImageParser.group_files()        │
    ├── generate_preview_thumbnail()     │
    │   (concurrent via ThreadPool)      │
    │                                    │
    ▼                                    │
  [user reviews & edits metadata]        │
    │                                    │
    ▼                                    ▼
process_import_group             ┌────────────────────────────┐
    │  (via JobRunner)           │  Batched Pipeline (per N)  │
    └───────────────────────────┤                            │
                                 │  1. prepare_single_image   │
                                 │     × N (ThreadPool)       │
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
    ├── prepare_single_image
    ├── generate_clip_embedding (single image)
    ├── save_to_database
    └── save_to_qdrant
```

## Functions

### `analyse_upload`

Parses and groups uploaded files for the preview UI. Called synchronously by the upload endpoint via `JobRunner.run_sync()`.

**Parameters:**
- `staging_dir: str` — path to staging directory
- `relative_paths: list[str]` — file paths within staging

**Processing:**
1. Creates an `ImageParser` with tag vocabulary from DB
2. Runs `parser.group_files(relative_paths)` to detect image groups
3. Generates preview thumbnails (120x120 JPEG) concurrently for each file into `{staging_dir}/.thumbs/`
4. Returns grouped results with per-file metadata and `preview_thumbnail` filenames

**Returns:** `list[dict]` — image groups with parsed metadata

### `process_import_group`

Processes a confirmed image group using the batched pipeline. Called async by the confirm endpoint via `JobRunner.submit()`.

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

### `process_import_job`

Processes all groups in a multi-group import. Wraps `process_import_group` for each group, tracking overall job progress.

### `process_single_image` (thin wrapper)

Processes one image end-to-end. Used for one-off processing; batch functions use the batched pipeline directly.

**Parameters:**
- `image_path: str` — absolute path to the source image
- `source_dir: str | None` — root directory for relative path computation (CLI ingest)
- `metadata: dict | None` — explicit metadata from web import (skips path parsing)

**Pipeline steps:**
1. `prepare_single_image` — parse, copy to store, thumbnails, colors
2. `generate_clip_embedding` — single-image CLIP inference
3. `save_to_database` — single-image DB save
4. `save_to_qdrant` — single-image Qdrant save

**Returns:** `{"status": "success"|"failed", "image_id": int, "filepath": str}`

### `bulk_image_ingestion`

Batch ingestion from one or more source directories (CLI entry point).

1. Builds parser once for all images (avoids per-image DB query)
2. For each source directory, scans for supported image files
3. Processes images in batches using the batched pipeline (same as `process_import_group`)
4. Returns summary: `{total_images, processed, successful, failed, results}`

## Key Task Functions

### `prepare_single_image`

The main per-image preparation function. Handles everything except CLIP and saves:

1. **Parse metadata** — CLI mode: `ImageParser.parse()`, Web mode: use explicit dict
2. **Copy to ImageStore** — UUID-based storage key, `image_store.put()`
3. **Get file size** — inline `os.stat()`
4. **Generate thumbnails** — calls `generate_thumbnails()` inline (3 sizes, BILINEAR for small/medium, LANCZOS for large). Also captures image dimensions.
5. **Extract colors** — calls `extract_dominant_colors()` inline (K-means, n_init=3, 5000 pixel sample)
6. **Grid detection** (optional) — calls `detect_grid_from_image()` inline when `enable_image_grid_detection=True`, battlemaps only, non-video. Uses hybrid constraint + autocorrelation algorithm. Only runs when filename-based detection left `gridded=None` (presence + size) or `gridded=True` with no dimensions (size only).

Returns a dict with `image_data`, `original_image_path`, `qdrant_metadata`, and `status`.

### `batch_generate_clip_embeddings`

Processes multiple images through CLIP in a single batch forward pass using `CLIPService.batch_encode_images()`. Sub-batches by `ingestion_batch_size` to manage memory.

### `batch_save_to_database`

Saves multiple images to SQLite in a single session/transaction using shared `_save_image_to_db()` helper.

### `batch_save_to_qdrant`

Saves multiple embeddings to Qdrant in a single `batch_add_embeddings()` call.

## Performance Configuration

Settings in `backend/app/config.py`:

| Setting | Default | Purpose |
|---------|---------|---------|
| `ingestion_batch_size` | 16 | Images per batch for CLIP/DB/Qdrant operations |
| `max_concurrent_prepare` | 8 | Max concurrent `prepare_single_image` tasks |
| `color_kmeans_n_init` | 3 | K-means random initializations |
| `color_clustering_samples` | 5000 | Max pixels sampled for color extraction |
| `enable_image_grid_detection` | False | Enable image-analysis-based grid detection |
| `grid_min_cell_px` | 32 | Minimum grid cell size in pixels |
| `grid_max_cell_px` | 256 | Maximum grid cell size in pixels |
| `grid_detection_max_dim` | 1024 | Downsample to this before analysis |
| `grid_presence_threshold` | 0.3 | Confidence threshold for grid presence |
| `grid_size_threshold` | 0.15 | Threshold when presence already known |

Thumbnail resampling: BILINEAR for 150px and 400px, LANCZOS for 800px. Preview thumbnails use BILINEAR.

## Background Execution

All background work (imports, backfills, retagging, embedding rebuilds) runs through the **JobRunner** service (`backend/app/services/job_runner.py`):

- In-process `ThreadPoolExecutor` with configurable max workers (default 2)
- Jobs are submitted from API endpoints: `runner.submit(fn, *args, name="...")`
- Each job tracks status (`queued`, `running`, `completed`, `failed`), progress percentage, and result
- Jobs can accept a `progress_fn` callback for real-time progress updates
- Status is available via `/api/v1/jobs/` endpoints

Periodic maintenance (backup, staging cleanup) runs through the **Scheduler** (`backend/app/services/scheduler.py`), an asyncio-based periodic task runner started during FastAPI lifespan.

## CLI Entry Points

- `uv run python -m backend.pipeline.backfill_content_hash` — backfill content hashes
- `uv run python -m backend.pipeline.backfill_grid_detection` — backfill grid detection
- `uv run python -m backend.pipeline.reparse_names` — re-parse all names
- `uv run python -m backend.pipeline.retag_all_images` — retag all images
- `uv run python -m backend.pipeline.fix_orphaned_images` — fix orphaned images
- `uv run python -m backend.pipeline.maintenance` — run maintenance manually

## Staging Cleanup

Staging directories (`data/staging/{job_id}/`) are created on upload and include a `.thumbs/` subdirectory for preview thumbnails. They are cleaned up:
- At the end of `process_import_job` after all groups are processed
- By the periodic `cleanup_staging` scheduler task (every 6h, removes dirs older than 24h)
