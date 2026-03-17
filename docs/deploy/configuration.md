# Configuration Reference

Scene Atlas is configured through environment variables (or a `.env` file) and runtime settings accessible from the web UI.

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
| `IMAGE_LIBRARY_DIR` | `./images` | Original image files (read by the app) |
| `DATABASE_URL` | *(derived from APP_DATA_DIR)* | SQLite database path — override only for non-standard layouts |

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
| `EMBEDDING_MODEL` | `clip-vit-b-32` | Active model subdirectory: `clip-vit-b-32` (small), `siglip2-base` (medium), `siglip2-so400m` (large) |
| `INFERENCE_DEVICE` | `auto` | Inference device: `auto`, `cpu`, `cuda`, `directml`, `coreml` |
| `CLIP_TEXT_CACHE_MAX` | `256` | Max cached text embeddings (LRU cache) |

### Performance

| Variable | Default | Description |
|----------|---------|-------------|
| `COLOR_CACHE_TTL_SECONDS` | `60` | Colour index cache expiry in seconds |
| `JOB_RETENTION_SECONDS` | `3600` | How long completed job records are kept |

## Runtime Settings (Web UI)

These settings are accessible from **Settings** in the web UI and are stored in the database. Changes take effect immediately unless noted.

### Import Processing

| Setting | Default | Description |
|---------|---------|-------------|
| Convert to WebP | On | Convert imported images to WebP for storage efficiency |
| WebP lossless | On | Use lossless WebP compression |
| WebP quality | 95 | Quality for lossy WebP (0–100, only used when lossless is off) |
| Max file size | 2 GB | Maximum size per uploaded file |
| Max video file size | 2 GB | Maximum size per video file |
| Max files per import | 1,000 | Maximum number of files in a single import |
| Max total import size | 2 GB | Maximum total size of all files in a single import |

### Grid Detection

| Setting | Default | Description |
|---------|---------|-------------|
| Enable image grid detection | On | Run image-analysis grid detection (in addition to filename-based) |
| Grid min cell size | 32 px | Minimum grid cell size to detect |
| Grid max cell size | 320 px | Maximum grid cell size to detect |
| Grid detection max dimension | 20,000 px | Skip grid detection for images larger than this |
| Grid presence threshold | 0.20 | Confidence threshold for detecting grid presence |
| Grid size threshold | 0.15 | Confidence threshold for grid dimension detection |
| Grid period ratio threshold | 0.98 | Autocorrelation ratio for period detection |
| Hex rotation confidence | 0.20 | Confidence penalty for hex grid rotation detection |

### Colour Extraction

| Setting | Default | Description |
|---------|---------|-------------|
| Dominant colours | 5 | Number of dominant colours to extract per image |
| Colour distance threshold | 0.35 | LAB colour distance threshold for search matching |
| Clustering samples | 5,000 | Number of pixel samples for K-means clustering |
| K-means initializations | 3 | Number of K-means restarts for stability |

### Performance Tuning

| Setting | Default | Description |
|---------|---------|-------------|
| Ingestion batch size | 16 | Images processed per batch during import |
| Max concurrent prepare tasks | 8 | Parallel thumbnail/colour/grid workers (resource-aware) |
| Max concurrent heavy requests | 4 | Parallel heavy API request limit (resource-aware) |
| Max job workers | 2 | Background job thread pool size (requires restart) |
| Scheduler enabled | On | Run automated backup and maintenance tasks |

## Model Selection

The `EMBEDDING_MODEL` environment variable (or the Settings UI) controls which AI model is used for search:

| Value | Model | Dimensions | Notes |
|-------|-------|-----------|-------|
| `clip-vit-b-32` | CLIP ViT-B/32 | 512 | Default. CPU-friendly. Good quality. |
| `siglip2-base` | SigLIP2-base | 768 | Better accuracy. GPU recommended. |
| `siglip2-so400m` | SigLIP2-so400m | 1152 | Best accuracy. GPU strongly recommended. |

Changing the active model triggers automatic re-embedding of all images. This runs in the background and can take some time for large libraries.

## Inference Device

The `INFERENCE_DEVICE` variable controls GPU acceleration:

| Value | Behaviour |
|-------|-----------|
| `auto` | Try CUDA → DirectML → CoreML → CPU (default) |
| `cpu` | Force CPU-only inference |
| `cuda` | Force NVIDIA CUDA (requires CUDA drivers) |
| `directml` | Force DirectML (Windows, any GPU) |
| `coreml` | Force CoreML (macOS, Apple Silicon) |
