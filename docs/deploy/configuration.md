# Configuration Reference

Scene Atlas is configured through environment variables (or a `.env` file) and runtime settings in the web UI.

## Environment Variables

Set these in your `.env` file, Docker Compose environment, or system environment.

### Core

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `8000` | Port for the web UI and API |
| `APP_MODE` | `auto` | Force mode: `server`, `electron`, or `auto` |
| `DEBUG` | `false` | Enable debug-level logging |

### Storage

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_DATA_DIR` | `./data` | Database, vector index, thumbnails, staging, backups |
| `IMAGE_LIBRARY_DIR` | `./images` | Managed image storage (Scene Atlas writes its file structure here) |
| `DATABASE_URL` | *(derived from APP_DATA_DIR)* | SQLite database path. Override only for non-standard layouts |

::: info Docker deployments
In Docker, use `IMAGE_DIR` in your `.env` to set the host-side bind mount path. Inside the container, this is mapped to `IMAGE_LIBRARY_DIR=/app/images`.
:::

### CORS

| Variable | Default | Description |
|----------|---------|-------------|
| `CORS_ORIGINS` | `["http://localhost:8000"]` | JSON array of allowed origins. Set to your domain when behind a reverse proxy |

### Authentication

| Variable | Default | Description |
|----------|---------|-------------|
| `AUTH_TOKEN` | *(unset)* | Bearer token for API authentication. When set, all requests require `Authorization: Bearer <token>` |

### AI Models

| Variable | Default | Description |
|----------|---------|-------------|
| `EMBEDDING_MODEL` | *(auto-detected)* | Active model: `small`, `medium`, or `large`. If unset, auto-selects based on GPU availability |
| `INFERENCE_DEVICE` | `auto` | Inference device: `auto`, `cpu`, `cuda`, `directml`, `coreml` |
| `CLIP_TEXT_CACHE_MAX` | `256` | Max cached text embeddings (LRU cache) |

### Performance

| Variable | Default | Description |
|----------|---------|-------------|
| `COLOR_CACHE_TTL_SECONDS` | `60` | Colour index cache expiry in seconds |
| `JOB_RETENTION_SECONDS` | `3600` | How long completed job records are kept |

## Runtime Settings (Web UI)

These settings are accessible from **Settings** in the web UI and stored in the database. Changes take effect immediately unless noted.

### Import Processing

| Setting | Default | Description |
|---------|---------|-------------|
| Stored format | Original | Format new imports are stored in: Original, WebP, JPEG or PNG (see [Importing](/guide/importing#stored-format)) |
| Quality | 90 | Quality for WebP and JPEG (1-100) |
| Lossless WebP for PNGs | On | Store lossless sources as lossless WebP; JPEGs always use the quality setting |
| Max file size | 2 GB | Maximum size per uploaded file |
| Max video file size | 2 GB | Maximum size per video file |
| Max files per import | 1,000 | Maximum entries in one uploaded ZIP archive |
| Max total import size | 2 GB | Maximum unpacked size of one uploaded ZIP archive |

### Grid Detection

| Setting | Default | Description |
|---------|---------|-------------|
| Enable image grid detection | On | Run image-analysis grid detection (in addition to filename-based) |
| Grid min cell size | 32 px | Minimum grid cell size to detect |
| Grid max cell size | 320 px | Maximum grid cell size to detect |
| Grid detection max dimension | 20,000 px | Skip grid detection for images larger than this |
| Grid presence threshold | 0.20 | Confidence threshold for grid presence |
| Grid size threshold | 0.15 | Confidence threshold for grid dimensions |
| Grid period ratio threshold | 0.98 | Autocorrelation ratio for period detection |
| Hex rotation confidence | 0.20 | Confidence penalty for hex grid rotation |

### Colour Extraction

| Setting | Default | Description |
|---------|---------|-------------|
| Dominant colours | 5 | Colours extracted per image |
| Colour distance threshold | 0.35 | LAB distance threshold for colour search matching |
| Clustering samples | 5,000 | Pixel samples for colour clustering |
| Clustering restarts | 3 | Number of clustering restarts for stability |

### Performance Tuning

| Setting | Default | Description |
|---------|---------|-------------|
| Ingestion batch size | 16 | Images processed per batch during import |
| Max concurrent prepare tasks | 8 | Parallel thumbnail/colour/grid workers (auto-scaled to available CPU/RAM) |
| Max concurrent heavy requests | 4 | Parallel heavy API request limit (auto-scaled) |
| Max job workers | 2 | Background job thread pool size (requires restart) |
| Scheduler enabled | On | Run automated backup and maintenance tasks |

## Model Details

The `EMBEDDING_MODEL` variable (or the Settings UI) controls which AI model is used for search. The app downloads the selected model from HuggingFace on first use.

| Value | Architecture | Embedding dimensions | Download size | Notes |
|-------|-------------|---------------------|---------------|-------|
| `small` | CLIP ViT-B/32 | 512 | ~250 MB | CPU-friendly. Good baseline quality |
| `medium` | SigLIP2-base | 768 | ~500 MB | Better accuracy. Works on CPU, faster with GPU |
| `large` | SigLIP2-so400m | 1152 | ~1 GB | Best accuracy. GPU strongly recommended |

Changing the active model triggers automatic re-embedding of all images. This runs in the background and can take time for large libraries.

## How Hybrid Search Ranking Works

When a hybrid search runs, three independent result sets (keyword, semantic, alias) are merged using Reciprocal Rank Fusion (RRF). Each result gets a score of `1 / (k + rank)` from each strategy it appeared in, and scores are summed. This means an image that ranks well across multiple strategies is boosted to the top, without any single strategy dominating.

## Inference Device

The `INFERENCE_DEVICE` variable controls GPU acceleration:

| Value | Behaviour |
|-------|-----------|
| `auto` | Try CUDA, then DirectML, then CoreML, then CPU (default) |
| `cpu` | Force CPU-only inference |
| `cuda` | Force NVIDIA CUDA (requires CUDA drivers) |
| `directml` | Force DirectML (Windows, any GPU) |
| `coreml` | Force CoreML (macOS, Apple Silicon) |
