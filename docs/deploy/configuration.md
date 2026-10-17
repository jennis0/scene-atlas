# Configuration Reference

Scene Atlas is configured through environment variables (or a `.env` file) and runtime settings in the web UI.

## Environment Variables

Set these in your `.env` file, Docker Compose environment, or system environment. Names are case-insensitive. Changes require a restart.

### Core

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_MODE` | `server` | `server` for standalone/Docker, `app` when run as the desktop sidecar (set by the desktop app) |
| `DEBUG` | `false` | Enable debug-level logging |
| `PORT` | `8000` | **Docker only:** host port published by `docker-compose.yml`. For standalone runs, pass `--port` to uvicorn |

### Storage

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_DATA_DIR` | `./data` | Database (`battlemap.db`), vector index, thumbnails, staging, logs |
| `IMAGE_LIBRARY_DIR` | `./images` | Managed image storage (Scene Atlas writes its own file structure here) and backups (`backups/`) |

The database path, vector index, thumbnail and staging directories are always derived from these two roots and cannot be overridden individually.

::: info Docker deployments
In Docker, use `IMAGE_DIR` in your `.env` to set the host-side bind mount path. Inside the container, this is mapped to `IMAGE_LIBRARY_DIR=/app/images`.
:::

### Network

| Variable | Default | Description |
|----------|---------|-------------|
| `CORS_ORIGINS` | `["http://localhost:3000","http://localhost:5173","http://localhost:8000"]` (Docker Compose: `["http://localhost:8000"]`) | JSON array of allowed origins. Set to your domain when behind a reverse proxy |

### Authentication

Scene Atlas has **no built-in authentication**. In server mode, anyone who can reach the port has full access, including deleting the library. Run it only behind a reverse proxy that authenticates users (basic auth, forward-auth, or an OAuth proxy) and never expose it directly to the internet. See [Docker Server: Reverse Proxy](/deploy/server#reverse-proxy).

### AI Models

| Variable | Default | Description |
|----------|---------|-------------|
| `EMBEDDING_MODEL` | *(unset)* | Force the active model: `small`, `medium`, or `large`. If unset, the model chosen in the UI is used; on first run, `medium` is suggested when a GPU is available and `small` otherwise |
| `INFERENCE_DEVICE` | `auto` | Inference device: `auto`, `cpu`, `cuda`, `directml`, `coreml` |
| `CLIP_TEXT_CACHE_MAX` | `256` | Max cached text embeddings (LRU cache) |

### Import

| Variable | Default | Description |
|----------|---------|-------------|
| `CONVERT_TO_WEBP` | `0` | Initial value of the "Convert to WebP" setting, used only when settings are first seeded |
| `MAX_IMPORT_ITEMS` | `50000` | Most files a single import job may contain |
| `MAX_IMAGE_PIXELS` | `1000000000` | Largest image (in pixels) that will be decoded; larger files are rejected |
| `PIXEL_HASH_MAX_PIXELS` | `100000000` | JPEGs above this size are decoded at reduced scale and skip the decoded-pixel duplicate check |
| `INGEST_MEMORY_BUDGET_MB` | *(automatic)* | Memory reserved for concurrent image preparation. Automatic: half of RAM beyond a 2 GiB reserve |

### Performance and Limits

| Variable | Default | Description |
|----------|---------|-------------|
| `COLOR_CACHE_TTL_SECONDS` | `60` | Colour index cache expiry in seconds |
| `JOB_RETENTION_SECONDS` | `3600` | How long completed background job records are kept |
| `RATE_LIMIT_ENABLED` | `true` | Enable per-client rate limits on expensive and destructive endpoints |
| `RATE_LIMIT_EXPENSIVE` | `2/minute` | Limit for expensive operations |
| `RATE_LIMIT_DESTRUCTIVE` | `1/minute` | Limit for destructive operations |

## Runtime Settings

Runtime settings are stored in the database and seeded with the defaults below on first start. Settings marked **UI** can be changed under **Settings** in the web UI; the rest can be changed through the settings API (`PATCH /api/v1/settings/`, see `/docs` on a running server).

### Import

| Setting | Key | Default | Where |
|---------|-----|---------|-------|
| Convert to WebP | `convert_to_webp` | Off (or `CONVERT_TO_WEBP`) | UI |
| WebP lossless | `webp_lossless` | On | API |
| WebP quality | `webp_quality` | 95 | API |
| Max file size | `max_import_file_size` | 2 GB | UI |
| Max video file size | `max_video_file_size` | 2 GB | UI |
| Max files per ZIP | `max_import_files` | 1,000 | UI (labelled "Max files per import") |
| Max uncompressed ZIP size | `max_import_total_size` | 2 GB | UI (labelled "Max total upload size") |

::: warning
The current import pipeline stores files as uploaded. The WebP settings are saved but not applied.

`max_import_files` and `max_import_total_size` are only enforced when a ZIP archive is expanded. The overall per-job file limit is the `MAX_IMPORT_ITEMS` environment variable.
:::

### Grid Detection

| Setting | Key | Default | Where |
|---------|-----|---------|-------|
| Enable image grid detection | `enable_image_grid_detection` | On | UI |
| Grid min cell size | `grid_min_cell_px` | 32 px | API |
| Grid max cell size | `grid_max_cell_px` | 320 px | API |
| Grid detection max dimension | `grid_detection_max_dim` | 8,000 px | API |
| Grid presence threshold | `grid_presence_threshold` | 0.20 | API |
| Grid size threshold | `grid_size_threshold` | 0.15 | API |
| Grid period ratio threshold | `grid_period_ratio_threshold` | 0.98 | API |
| Hex rotation confidence | `grid_hex_rot_conf` | 0.20 | API |

Image grid detection runs on battlemaps only, in addition to filename-based detection. Larger images are downscaled to `grid_detection_max_dim` for analysis.

### Colour Extraction

| Setting | Key | Default | Where |
|---------|-----|---------|-------|
| Dominant colours | `num_dominant_colors` | 5 | API |
| Colour distance threshold | `color_distance_threshold` | 0.35 | API |
| Clustering samples | `color_clustering_samples` | 5,000 | API |
| Clustering restarts | `color_kmeans_n_init` | 3 | API |

### Performance

| Setting | Key | Default | Where |
|---------|-----|---------|-------|
| Ingestion batch size | `ingestion_batch_size` | 16 | API |
| Concurrent imports | `max_concurrent_prepare` | min(CPUs, 8, RAM-based cap) | UI |
| Max concurrent heavy requests | `max_concurrent_heavy_requests` | min(max(1, CPUs/2), 6) | API (restart) |
| Max job workers | `max_job_workers` | min(4, CPUs/2), at least 1 | API |
| Scheduler enabled | `scheduler_enabled` | On | API (restart) |

The concurrency defaults are computed from the host's CPU count and total RAM when settings are first seeded. The scheduler runs the daily backup and maintenance tasks.

## Model Details

The active model is chosen in **Settings** (or forced with `EMBEDDING_MODEL`). The app downloads the selected model from HuggingFace on first use.

| Value | Architecture | Embedding dimensions | Download size | Notes |
|-------|-------------|---------------------|---------------|-------|
| `small` | CLIP ViT-B/32 | 512 | ~250 MB | CPU-friendly. Good baseline quality |
| `medium` | SigLIP2-base | 768 | ~500 MB | Better accuracy. Works on CPU, faster with GPU |
| `large` | SigLIP2-so400m | 1152 | ~1 GB | Best accuracy. GPU strongly recommended |

Changing the active model triggers automatic re-embedding of all images. This runs in the background and can take time for large libraries.

## How Hybrid Search Ranking Works

When a hybrid search runs, three independent result sets (keyword, semantic, alias) are merged using Reciprocal Rank Fusion (RRF). Each result gets `weight / (k + rank)` from each strategy it appeared in (k = 60; weights: keyword 1.1, semantic 1.0, alias 0.5, so synonyms never outrank the words you typed), and the scores are summed. An image that ranks well across several strategies rises to the top without any single strategy dominating.

## Inference Device

The `INFERENCE_DEVICE` variable controls GPU acceleration:

| Value | Behaviour |
|-------|-----------|
| `auto` | Try CUDA, then DirectML, then CoreML, then CPU (default) |
| `cpu` | Force CPU-only inference |
| `cuda` | Force NVIDIA CUDA (requires CUDA drivers) |
| `directml` | Force DirectML (Windows, any GPU) |
| `coreml` | Force CoreML (macOS, Apple Silicon) |
