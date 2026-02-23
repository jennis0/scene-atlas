# Backend Architecture

## Overview

The backend is a **FastAPI** application serving a REST API for image management, search, and import. It connects to SQLite (relational data), Qdrant (vector embeddings), and the filesystem (image/thumbnail storage).

## Directory Structure

```
backend/
├── app/
│   ├── api/              # API route handlers
│   │   ├── images.py     # CRUD + file serving for images
│   │   ├── imports.py    # Web import upload/confirm/status
│   │   ├── search.py     # Text, filter, and semantic search
│   │   └── tags.py       # Tag categories and tag CRUD
│   ├── models/
│   │   ├── database.py   # SQLAlchemy models + DB setup + seed data
│   │   └── schemas.py    # Pydantic request/response schemas
│   ├── services/
│   │   ├── image_parser.py      # Filename/path metadata parser
│   │   ├── clip_service.py      # CLIP model for embeddings
│   │   ├── image_store.py       # Hash-sharded filesystem storage
│   │   └── qdrant_service.py    # Qdrant vector DB client
│   ├── config.py         # Pydantic settings (env-driven)
│   └── main.py           # FastAPI app creation, router mounting, startup
├── flows/
│   ├── ingestion.py      # Prefect flows: process_single_image, bulk_image_ingestion
│   ├── deploy.py         # Prefect deployment registration
│   └── tasks/
│       ├── color_extraction.py      # K-means dominant color extraction
│       ├── embedding_generation.py  # CLIP embedding generation
│       ├── image_processing.py      # Thumbnails, dimensions, file size
│       └── metadata_extraction.py   # Upload metadata helper (uses parser)
└── tests/
```

## API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/v1/images/` | List images (paginated) |
| GET | `/api/v1/images/{id}` | Get single image |
| DELETE | `/api/v1/images/{id}` | Delete image + files |
| GET | `/api/v1/images/{id}/scenes` | Get group members (scenes) |
| GET | `/api/v1/images/{id}/file` | Serve original image file |
| GET | `/api/v1/images/{id}/thumbnail` | Serve thumbnail (falls back to original) |
| GET | `/api/v1/search/` | Multi-faceted search (text, tags, colors, semantic) |
| GET | `/api/v1/search/semantic` | Pure semantic search via CLIP |
| GET | `/api/v1/tags/categories` | List tag categories |
| GET | `/api/v1/tags/values/{category}` | List values for a category |
| POST | `/api/v1/tags/image/{id}` | Add tag to image |
| DELETE | `/api/v1/tags/{tag_id}` | Remove a tag |
| GET | `/api/v1/tags/stats` | Tag statistics |
| POST | `/api/v1/imports/upload` | Upload files for import analysis |
| POST | `/api/v1/imports/{job_id}/confirm` | Confirm a group for processing |
| GET | `/api/v1/imports/{job_id}/status` | Check import job progress |

## Services

### ImageStore
Hash-sharded object store. Interface: `put(key, path)`, `get_path(key)`, `delete(key)`, `exists(key)`. Two instances: one for images, one for thumbnails. See [storage.md](storage.md).

### CLIPService
Singleton wrapping HuggingFace CLIP ViT-B/32. Lazy-loaded on first use. Methods: `encode_image(path) -> [float]`, `encode_text(query) -> [float]`, `batch_encode_images(paths)`.

### QdrantService
Client for the Qdrant vector DB. Manages the `battlemap_images` collection. Methods: `add_image_embedding`, `search_similar`, `delete_image_embedding`.

### ImageParser
Filename/path parser with DB-driven tag vocabulary. See [parser.md](parser.md).

## Configuration

All config via `backend/app/config.py` using `pydantic-settings`. Reads from `.env` file. Key settings:

- `database_url` — SQLite path (default: `sqlite:///./data/battlemap.db`)
- `store_images_dir` / `store_thumbnails_dir` — object store base directories
- `staging_dir` — temp directory for import uploads
- `qdrant_path` — Qdrant embedded local storage directory
- `clip_model_name` / `clip_device` — CLIP model config
- `max_job_workers` — concurrent background job threads
- `scheduler_enabled` — periodic maintenance (backup, staging cleanup)
- `cors_origins` — allowed origins (localhost:3000, localhost:5173)

## Startup Sequence

1. FastAPI app created in `main.py`
2. On startup: create DB engine, run `init_db()` (create tables), run `seed_tag_categories()` (upsert vocabulary)
3. Pre-load CLIP model, start JobRunner (background thread pool), start Scheduler (periodic tasks)
4. Store DB engine in `app.state.db_engine` for dependency injection
5. Routes mounted with `/api/v1` prefix

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
