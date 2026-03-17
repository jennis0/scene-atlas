# Ingestion Pipeline

## Overview

The ingestion pipeline processes images from the filesystem into the system: parsing metadata, copying into the object store, generating thumbnails, extracting colors, generating CLIP embeddings, and saving everything to SQLite + LanceDB.

All ingestion runs through functions defined in `backend/pipeline/ingestion.py`. Background execution is handled by the in-process `JobRunner` (ThreadPoolExecutor).

## Pipeline Architecture

The pipeline uses a **batched stage architecture** for maximum throughput. Images are processed in configurable batches (default 16) where:
- **Prepare stage** runs concurrently via `ThreadPoolExecutor` (thumbnails + colors per image)
- **CLIP embedding** runs as a batch forward pass (vectorized, 3-5x faster than individual)
- **Database and LanceDB saves** are batched into single transactions

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
  [auto-confirm]                          │
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
                                 │  4. batch_save_to_vector_db│
                                 │     (single upsert call)   │
                                 └────────────────────────────┘

process_single_image (thin wrapper for one-off use)
    ├── prepare_single_image
    ├── generate_clip_embedding (single image)
    ├── save_to_database
    └── save_to_vector_db
```

## Functions

### `analyse_upload`

Parses and groups uploaded files for the preview UI. Called via `asyncio.to_thread(analyse_upload, ...)`.

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
   - Runs `batch_save_to_vector_db` in a single upsert call
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
4. `save_to_vector_db` — single-image LanceDB save

**Returns:** `{"status": "success"|"failed", "image_id": int, "filepath": str}`

### `bulk_image_ingestion`

Batch ingestion from one or more source directories (CLI entry point).

1. Builds parser once for all images (avoids per-image DB query)
2. For each source directory, scans for supported image files
3. Processes images in batches using the batched pipeline (same as `process_import_group`)
4. Returns summary: `{total_images, processed, successful, failed, results}`

## Embedding Reuse

When re-importing a file with the same content hash as an existing image, the pipeline retrieves the existing CLIP embedding from LanceDB instead of regenerating it. This avoids redundant CLIP inference for duplicate files. The existing embedding is looked up by `image_id` of the original image and copied to the new image's LanceDB row.

## Video Support

The pipeline supports video files in addition to images:
- **First-frame extraction:** For CLIP embedding generation, the first frame of a video is extracted as a JPEG and used as the input image
- **File size limits:** Videos have a separate configurable limit via `max_video_file_size` (distinct from image file size limits)
- **Media type tracking:** Each file is stored with a `media_type` field set to either `'image'` or `'video'` in the database
- Video frame extraction and dimension reading are handled by `backend/app/services/video_utils.py`

## Key Task Functions

### `prepare_single_image`

The main per-image preparation function. Handles everything except CLIP and saves:

1. **Parse metadata** — CLI mode: `ImageParser.parse()`, Web mode: use explicit dict
2. **Copy to ImageStore** — UUID-based storage key, `image_store.put()`
3. **Get file size** — inline `os.stat()`
4. **Generate thumbnails** — calls `generate_thumbnails()` inline (3 sizes, BILINEAR for small/medium, LANCZOS for large). Also captures image dimensions.
5. **Extract colors** — calls `extract_dominant_colors()` inline (K-means, n_init=3, 5000 pixel sample)
6. **Grid detection** (optional) — calls `detect_grid_from_image()` inline when `enable_image_grid_detection=True`, battlemaps only, non-video. Uses hybrid constraint + autocorrelation algorithm. Only runs when filename-based detection left `gridded=None` (presence + size) or `gridded=True` with no dimensions (size only).

Returns a dict with `image_data`, `original_image_path`, `vector_metadata`, and `status`.

### `batch_generate_clip_embeddings`

Processes multiple images through CLIP in a single batch forward pass using `CLIPService.batch_encode_images()`. Sub-batches by `ingestion_batch_size` to manage memory.

### `batch_save_to_database`

Saves multiple images to SQLite in a single session/transaction using shared `_save_image_to_db()` helper.

**Batch failure isolation:** If the batch DB transaction fails (e.g. constraint violation from a concurrent duplicate insert), the error is caught per-batch (the entire batch transaction either commits or rolls back). Each image in a failed batch is recorded with a `db_save` stage error in `ImportGroupJob.file_errors`, and processing continues for the remaining batches. This prevents a single bad batch from killing an entire import group.

**Per-batch CLIP failure isolation:** If batch CLIP embedding generation fails, all images in that batch are marked as failed, but other batches in the same group continue processing independently. This ensures a transient CLIP error (e.g. OOM on a large batch) does not abort the entire import group.

### `batch_save_to_vector_db`

Saves multiple embeddings to LanceDB in a single `batch_add_embeddings()` call.

## Performance Configuration

Settings in `backend/app/config.py`:

| Setting | Default | Purpose |
|---------|---------|---------|
| `ingestion_batch_size` | 16 | Images per batch for CLIP/DB/LanceDB operations |
| `max_concurrent_prepare` | 4 | Max concurrent `prepare_single_image` tasks (dynamically computed by `resource_detector.py` at first boot) |
| `color_kmeans_n_init` | 3 | K-means random initializations |
| `color_clustering_samples` | 5000 | Max pixels sampled for color extraction |
| `enable_image_grid_detection` | False | Enable image-analysis-based grid detection |
| `grid_min_cell_px` | 32 | Minimum grid cell size in pixels |
| `grid_max_cell_px` | 320 | Maximum grid cell size in pixels |
| `grid_detection_max_dim` | 20000 | Maximum image dimension for grid analysis |
| `grid_presence_threshold` | 0.3 | Confidence threshold for grid presence |
| `grid_size_threshold` | 0.15 | Threshold when presence already known |
| `grid_period_ratio_threshold` | 0.98 | Period ratio threshold for square vs hex classification |
| `grid_hex_rot_conf` | 0.20 | Confidence penalty for hex grid rotation |

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

## Import Job Lifecycle

After processing each group, `_finalize_import_job()` calls `transition_job_status()` to update the import job's status based on the state machine. See [import-state-machine.md](import-state-machine.md) for the full state machine design.

## Logging

Centralised logging is configured in `backend/app/logging_config.py` via `setup_logging(data_dir, debug)`. It is called once during app startup (from `main.py` and `entry.py`).

**Handlers:**
- **StreamHandler** (stdout) — console output, matches previous `basicConfig` behaviour
- **RotatingFileHandler** — writes to `{data_dir}/logs/scene-atlas.log`, rotated at 10 MB, 5 backups

**Format:** `%(asctime)s %(levelname)-8s [%(name)s] %(message)s`

Debug mode (`--debug` flag or `settings.debug`) sets both handlers to `DEBUG` level; otherwise `INFO`.

All pipeline modules use standard `logging.getLogger(__name__)` — no custom wrappers.

## Per-Image Error Capture

When an image fails during ingest, errors are classified into user-friendly messages by `backend/pipeline/error_classifier.py`.

**`classify_ingest_error(exc, stage)`** returns:
```python
{"reason": "Image is corrupt or not a supported format",  # user-facing
 "stage": "thumbnails",                                    # pipeline stage
 "detail": "cannot identify image file 'foo.png'"}         # raw exception
```

**Pipeline stages:** `parse`, `copy`, `thumbnails`, `colors`, `grid_detection`, `embedding`, `db_save`, `vector_db_save`

**Classification rules** (checked in order):
| Exception / Pattern | Reason |
|---|---|
| `UnidentifiedImageError` / "cannot identify image" | Image is corrupt or not a supported format |
| `DecompressionBombError` | Image is too large to process safely |
| "could not read image" (cv2) | Image could not be read for processing |
| `FileNotFoundError` | File was not found |
| `PermissionError` | File could not be accessed (permission denied) |
| `OSError` errno ENOSPC | Not enough disk space to process image |
| `MemoryError` | Image is too large to process (out of memory) |
| Stage = `embedding` | Failed to generate image embedding |
| Stage = `db_save` | Failed to save image to database |
| Stage = `vector_db_save` | Failed to save image embedding to search index |
| Fallback | Processing failed during {stage} |

**Storage:** Per-image errors are collected during `_run_group` and stored as a JSON list on `ImportGroupJob.file_errors` (Text column). Each entry has `filename`, `reason`, and `stage` keys.

**API:** The `ImportGroupStatus` schema includes a `file_errors: list[FileError]` field, populated from the DB column by the status endpoint. Phase 2 will display these in the frontend.

## Staging Cleanup

Staging directories (`data/staging/{job_id}/`) are created on upload and include a `.thumbs/` subdirectory for preview thumbnails. They are cleaned up by:
- The periodic `cleanup_staging` scheduler task (every 6h, removes dirs older than 24h)
- The `expire_stale_jobs` scheduler task (every 6h, cleans staging for expired jobs)
- `POST /cancel` endpoint and `_finalize_import_job()` pipeline function
