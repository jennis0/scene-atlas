# Configuration Reference

Scene Atlas is configured through environment variables (or a `.env` file) and runtime settings in the web UI.

## Environment Variables

Set these in your `.env` file, Docker Compose environment, or system environment. Names are case-insensitive. Changes require a restart.

### Core

| Variable | Default | Description |
|----------|---------|-------------|
| `SCENE_ATLAS_APP_MODE` | `server` | `server` for standalone/Docker, `app` when run as the desktop sidecar (set by the desktop app) |
| `SCENE_ATLAS_DEBUG` | `false` | Enable debug-level logging |
| `SCENE_ATLAS_PORT` | `8000` | **Docker only:** host port published by `docker-compose.yml`. For standalone runs, pass `--port` to uvicorn |

### Storage

| Variable | Default | Description |
|----------|---------|-------------|
| `SCENE_ATLAS_DATA_DIR` | `./data` | Database (`battlemap.db`), vector index, thumbnails, staging, logs |
| `SCENE_ATLAS_IMAGES_DIR` | `./images`, or `<SCENE_ATLAS_DATA_DIR>/images` when only `SCENE_ATLAS_DATA_DIR` is set | Managed image storage (Scene Atlas writes its own file structure here) and backups (`backups/`) |
| `SCENE_ATLAS_LINKED_LIBRARY_DIR` | unset | The linked library: a folder of your own maps that Scene Atlas reads where they are and never writes to. Optional; mount it read-only (e.g. `-v /srv/maps:/library:ro` with `SCENE_ATLAS_LINKED_LIBRARY_DIR=/library`). It may be missing at startup: its maps then show as unavailable until it's back. See [Linked library](/deploy/server#linked-library) |

A data folder that already has a database but no `images` folder (a library made before that default) keeps using `./images`, and the log says so; set `SCENE_ATLAS_IMAGES_DIR` or move the folder.

Each library is recognised by a `scene-atlas-library.json` file at the root of `SCENE_ATLAS_DATA_DIR` and `SCENE_ATLAS_IMAGES_DIR`. The backend refuses to start if the two folders belong to different libraries, if `SCENE_ATLAS_IMAGES_DIR` doesn't hold the maps the database expects (for example a drive that isn't mounted), or if either folder is `SCENE_ATLAS_LINKED_LIBRARY_DIR` or contains it. The log says which, on a line starting `STARTUP ERROR:`.

The database path, vector index, thumbnail and staging directories are always derived from these two roots and cannot be overridden individually.

Only one Scene Atlas backend can use a given `SCENE_ATLAS_DATA_DIR` or `SCENE_ATLAS_IMAGES_DIR` at a time. A second backend pointed at either folder refuses to start with "Another Scene Atlas backend is already using the folder …". The lock is a `.backend.lock` file in each folder; it is released automatically when the backend exits, so a leftover file is harmless.

::: info Docker deployments
In Docker, `SCENE_ATLAS_IMAGES_DIR` in `.env` is the folder on the host. Compose mounts it at `/app/images` and points the app there.
:::

### Network

| Variable | Default | Description |
|----------|---------|-------------|
| `SCENE_ATLAS_FORWARDED_ALLOW_IPS` | `127.0.0.1,::1` | Reverse proxies (comma-separated IPs or CIDR networks, or `*`) whose `X-Forwarded-For` header is trusted for the client IP used by rate limits. See [Client IP addresses](/deploy/server#client-ip-addresses-and-rate-limits) |
| `SCENE_ATLAS_CORS_ORIGINS` | `["http://localhost:3000","http://localhost:5173","http://localhost:8000"]` (Docker Compose: `["http://localhost:8000"]`) | JSON array of allowed origins. Set to your domain when behind a reverse proxy |

### Updates

| Variable | Default | Description |
|----------|---------|-------------|
| `SCENE_ATLAS_CHECK_FOR_UPDATES` | `true` | Server mode: ask GitHub (`api.github.com`) for the latest Scene Atlas release a minute after startup and then once a day, and show it to everyone in **Settings**. `false` makes no request. The desktop app ignores it and has its own setting |

The check sends no library data; GitHub sees the server's IP address and its Scene Atlas version (in the `User-Agent`).

### Authentication

Scene Atlas has **no built-in authentication**. In server mode, anyone who can reach the port has full access, including deleting the library. Run it only behind a reverse proxy that authenticates users (basic auth, forward-auth, or an OAuth proxy) and never expose it directly to the internet. See [Docker Server: Reverse Proxy](/deploy/server#reverse-proxy).

### AI Models

| Variable | Default | Description |
|----------|---------|-------------|
| `SCENE_ATLAS_EMBEDDING_MODEL` | *(unset)* | Force the active model: `small`, `medium`, or `large`. If unset, the model chosen in the UI is used; on first run, `medium` is suggested when a GPU is available and `small` otherwise |
| `SCENE_ATLAS_INFERENCE_DEVICE` | `auto` | Inference device: `auto`, `cpu`, `cuda`, `directml`, `coreml` |
| `SCENE_ATLAS_CLIP_TEXT_CACHE_MAX` | `256` | Max cached text embeddings (LRU cache) |

### Import

| Variable | Default | Description |
|----------|---------|-------------|
| `SCENE_ATLAS_CONVERT_TO_WEBP` | `0` | `1` seeds the Stored format setting as WebP, the setup wizard's starting choice; used only when settings are first seeded |
| `SCENE_ATLAS_MAX_IMPORT_ITEMS` | `50000` | Most files a single uploaded import may contain |
| `SCENE_ATLAS_MAX_LOCAL_IMPORT_ITEMS` | `250000` | Most files a desktop import read from disk may contain, and most new files one scan of `SCENE_ATLAS_LINKED_LIBRARY_DIR` adds |
| `SCENE_ATLAS_MAX_IMAGE_PIXELS` | `1000000000` | Largest image (in pixels) that will be decoded; larger files are rejected |
| `SCENE_ATLAS_PIXEL_HASH_MAX_PIXELS` | `100000000` | JPEGs above this size are decoded at reduced scale and skip the decoded-pixel duplicate check |
| `SCENE_ATLAS_INGEST_MEMORY_BUDGET_MB` | *(automatic)* | Memory reserved for concurrent image preparation. Automatic: half of RAM beyond a 2 GiB reserve |

### Performance and Limits

| Variable | Default | Description |
|----------|---------|-------------|
| `SCENE_ATLAS_JOB_RETENTION_SECONDS` | `3600` | How long completed background job records are kept |
| `SCENE_ATLAS_RATE_LIMIT_ENABLED` | `true` | Enable per-client rate limits on expensive and destructive endpoints |
| `SCENE_ATLAS_RATE_LIMIT_EXPENSIVE` | `2/minute` | Limit for expensive operations |
| `SCENE_ATLAS_RATE_LIMIT_DESTRUCTIVE` | `1/minute` | Limit for destructive operations |

## Runtime Settings

Runtime settings are stored in the database and seeded with the defaults below on first start. Settings marked **UI** can be changed under **Settings** in the web UI; the rest can be changed through the settings API (`PATCH /api/v1/settings/`, see `/docs` on a running server).

### Import Limits and Stored Format

| Setting | Key | Default | Where |
|---------|-----|---------|-------|
| Stored format | `stored_format` | Original (WebP if `SCENE_ATLAS_CONVERT_TO_WEBP=1`) | UI |
| Quality | `stored_quality` | 90 | UI |
| Lossless WebP for PNGs | `stored_lossless` | On | UI |
| Max file size | `max_import_file_size` | 2 GB | UI |
| Max video file size | `max_video_file_size` | 2 GB | UI |
| Max files per zip | `max_import_files` | 1,000 | UI |
| Max zip size (uncompressed) | `max_import_total_size` | 2 GB | UI |

Stored format is Original, WebP, JPEG or PNG and applies to new imports only (see [Importing](/guide/importing#stored-format)). Quality applies to WebP and JPEG (1-100); JPEG sources always use it.

Despite their names, `max_import_files` and `max_import_total_size` apply to each ZIP archive, not to a whole import. The per-import file limits are the `SCENE_ATLAS_MAX_IMPORT_ITEMS` and `SCENE_ATLAS_MAX_LOCAL_IMPORT_ITEMS` environment variables.

### Linked library

| Setting | Key | Default | Where |
|---------|-----|---------|-------|
| Check for changes | `linked_rescan_minutes` | 15 | UI |

How often `SCENE_ATLAS_LINKED_LIBRARY_DIR` is scanned for added, moved and deleted maps: 5, 15 or 60 minutes, or 0 for only when the backend starts. "Check for changes" in Settings scans at any time. A scan that finds nothing new reads no files.

### Grid Detection

| Setting | Key | Default | Where |
|---------|-----|---------|-------|
| Grid detection | `enable_image_grid_detection` | On | UI |
| Grid analysis resolution | `grid_analysis_max_dim` | 0 (full resolution) | UI |

Image grid detection runs on battlemaps only, in addition to filename-based detection. A non-zero `grid_analysis_max_dim` downscales larger images before analysis: faster, but it can miss thin grid lines on high-resolution maps.

### Colour Extraction

| Setting | Key | Default | Where |
|---------|-----|---------|-------|
| Dominant colours | `num_dominant_colors` | 5 | API |
| Colour match | `color_distance_threshold` | 25 (delta E) | UI (Close 12, Similar 25, Broad 40); any value through the API |
| Clustering samples | `color_clustering_samples` | 5,000 | API |
| Clustering restarts | `color_kmeans_n_init` | 3 | API |

The colour distance threshold is a CIE76 delta E between 0 and 100 (lower is stricter). Before migration 024 it was an HSL distance with a default of 0.35; upgrading maps 0.35 to 25 and scales custom values by the same ratio.

### Performance

| Setting | Key | Default | Where |
|---------|-----|---------|-------|
| Ingestion batch size | `ingestion_batch_size` | 16 | API |
| Parallel image processing | `max_concurrent_prepare` | min(CPUs, 8, RAM-based cap) | UI (restart) |
| Max concurrent heavy requests | `max_concurrent_heavy_requests` | min(max(1, CPUs/2), 6) | API (restart) |
| Max job workers | `max_job_workers` | min(4, CPUs/2), at least 1 | API |
| Scheduler enabled | `scheduler_enabled` | On | API (restart) |

Parallel image processing is how many images are prepared at once (hashing, thumbnails, colours, grid detection), shared by all running imports rather than a number of simultaneous imports. Import memory use is also capped by `SCENE_ATLAS_INGEST_MEMORY_BUDGET_MB`. The concurrency defaults are computed from the host's CPU count and total RAM when settings are first seeded. The scheduler runs the daily backup and maintenance tasks.

## Model Details

The active model is chosen in **Settings** (or forced with `SCENE_ATLAS_EMBEDDING_MODEL`). The app downloads the selected model from HuggingFace on first use.

| Value | Architecture | Embedding dimensions | Download size | Notes |
|-------|-------------|---------------------|---------------|-------|
| `small` | CLIP ViT-B/32 | 512 | ~100 MB | CPU-friendly. Good baseline quality |
| `medium` | SigLIP2-base | 768 | ~150 MB | Better accuracy. Works on CPU, faster with GPU |
| `large` | SigLIP2-large | 1024 | ~680 MB | Best accuracy. GPU strongly recommended |

Changing the active model triggers automatic re-embedding of all images. This runs in the background and can take time for large libraries.

For how search ranks results and matches colours, see [How Search Works](/reference/search).

## Inference Device

The `SCENE_ATLAS_INFERENCE_DEVICE` variable controls GPU acceleration:

| Value | Behaviour |
|-------|-----------|
| `auto` | Try CUDA, then DirectML, then CoreML, then CPU (default) |
| `cpu` | Force CPU-only inference |
| `cuda` | Force NVIDIA CUDA (requires CUDA drivers) |
| `directml` | Force DirectML (Windows, any GPU) |
| `coreml` | Force CoreML (macOS, Apple Silicon) |
