# Ingestion Pipeline

## Overview

The ingestion pipeline processes images from the filesystem into the system: parsing metadata, copying into the object store, generating thumbnails, extracting colors, generating CLIP embeddings, and saving everything to SQLite + Qdrant.

All ingestion runs through **Prefect** flows defined in `backend/flows/ingestion.py`. All flow and task parameters use primitive types (strings, dicts, lists) for JSON serialization compatibility with Prefect deployments.

## Flow Architecture

```
Web Upload                              CLI
    │                                    │
    ▼                                    ▼
analyse_upload (deployment)     bulk_image_ingestion (flow)
    │                                    │
    ├── BattlemapParser.group_files()    │
    ├── generate_preview_thumbnail()     │
    │                                    │
    ▼                                    │
  [user reviews & edits metadata]        │
    │                                    │
    ▼                                    │
process_import_group (deployment)        │
    │                                    │
    ├─── process_single_image ◄──────────┘
    │        ├── get_image_dimensions (task)
    │        ├── get_file_size (task)
    │        ├── generate_thumbnails (task)
    │        ├── extract_dominant_colors (task)
    │        ├── generate_clip_embedding (task)
    │        ├── save_to_database (task, retries=2)
    │        └── save_to_qdrant (task, retries=2)
    │
    └─── update_import_job_progress (task)
```

## Flows

### `analyse_upload` (Prefect deployment)

Parses and groups uploaded files for the preview UI. Called synchronously by the upload endpoint via `run_deployment(timeout=120)`.

**Parameters:**
- `staging_dir: str` — path to staging directory
- `relative_paths: list[str]` — file paths within staging

**Processing:**
1. Creates a `BattlemapParser` with tag vocabulary from DB
2. Runs `parser.group_files(relative_paths)` to detect variant groups
3. Generates preview thumbnails (120x120 JPEG) for each file into `{staging_dir}/.thumbs/`
4. Returns grouped results with per-file metadata and `preview_thumbnail` filenames

**Returns:** `list[dict]` — variant groups with parsed metadata (persisted result for cross-process retrieval)

### `process_import_group` (Prefect deployment)

Processes a confirmed variant group end-to-end. Called async by the confirm endpoint via `run_deployment(timeout=0)`.

**Parameters:**
- `job_id: str` — ImportJob ID for progress tracking
- `staging_dir: str` — path to staging directory
- `author: str` — user-confirmed author
- `variant_group_name: str` — user-confirmed group name
- `files: list[dict]` — per-file metadata dicts from the confirm request, each containing:
  - `relative_path: str`
  - `tags: list[dict]` (category, value, confidence, source)
  - `gridded: bool | None`
  - `grid_width: int | None`
  - `grid_height: int | None`
  - `sub_variant: str | None`

**Processing:**
For each file, calls `process_single_image` with a `metadata` dict built directly from the confirm data — no re-parsing of filenames. The metadata includes `author`, `variant_group_name`, and all per-file fields from the confirm request.

**Side effects:** Updates `ImportJob.processed_files` / `failed_files` after each image.

**Returns:** `dict` with `{job_id, processed, failed, total}`

### `process_single_image` (Prefect subflow)

The core unit of work. Processes one image file end-to-end.

**Parameters:**
- `image_path: str` — absolute path to the source image
- `source_dir: str | None` — root directory for relative path computation (CLI ingest)
- `metadata: dict | None` — explicit metadata from web import (skips path parsing)

**Pipeline steps:**

```
1. Parse metadata
   ├── CLI mode: BattlemapParser.parse(relative_path)
   │   → author, variant_group_name, sub_variant, gridded, grid_width, grid_height, tags
   └── Web import mode: use explicit metadata dict directly
       (all fields provided by the user via the preview UI)

2. Copy into ImageStore
   → Generate UUID-based storage_key
   → image_store.put(storage_key, image_path)

3. Get image properties (Prefect task, retries=2)
   → width, height via PIL
   → file_size via os.stat

4. Generate thumbnails (Prefect task, retries=2)
   → 150x150, 400x400, 800x800
   → Saved to ThumbnailStore with key "{stem}_{WxH}.jpg"

5. Extract dominant colors (Prefect task, retries=2)
   → K-means clustering on downsampled pixels
   → Returns top 5 colors as hex + percentage

6. Generate CLIP embedding (Prefect task, retries=2)
   → CLIPService.encode_image(path)
   → 512-dim normalized vector

7. Save to database (Prefect task, retries=2)
   → Upsert Image row (keyed on storage_key)
   → Create/find VariantGroup (keyed on base_name + author)
   → Replace tags and colors

8. Save to Qdrant (Prefect task, retries=2)
   → qdrant_service.add_image_embedding(image_id, embedding, metadata)
```

**Returns:** `{"status": "success"|"failed", "image_id": int, "filepath": str}`

### `bulk_image_ingestion` (Prefect flow)

Batch ingestion from one or more source directories (CLI entry point).

1. For each source directory, run `scan_directory` task
2. `scan_directory` recursively finds supported image files, skipping `__MACOSX` dirs and `._` files
3. For each image, call `process_single_image(image_path, source_dir=directory)`
4. Returns summary: `{total_images, processed, successful, failed, results}`

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
