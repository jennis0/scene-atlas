# Scene Atlas

A local system for managing, searching, and exploring large collections of RPG battlemap images.

## Features

- **Hybrid search** — natural-language semantic search (CLIP) combined with keyword full-text search (FTS5 + Porter stemmer)
- **Tag-based filtering** — grid state, season, lighting, weather, terrain, and more; auto-extracted from filenames
- **Variant groups** — related maps (different lighting, grid, weather variants) grouped automatically from name and folder structure
- **Web import** — drag-and-drop uploader with browser-side duplicate detection, ZIP support, and preview
- **Color search** — filter by dominant colours extracted from each image
- **100% local** — no cloud services; runs on your home server or laptop

## Tech Stack

| Layer | Technology |
|---|---|
| Backend API | FastAPI + SQLAlchemy (SQLite) |
| Semantic search | CLIP ViT-B/32 → Qdrant vector DB |
| Full-text search | SQLite FTS5 with Porter stemmer |
| Orchestration | Prefect 3 (scheduled + on-demand flows) |
| Frontend | React 18 + TypeScript + Vite + Tailwind + Radix UI |
| Infrastructure | Docker Compose (Qdrant, Prefect server, Postgres, Redis) |

---

## Prerequisites

- **Python 3.11+** with [uv](https://docs.astral.sh/uv/)
- **Node.js 20+** with npm
- **Docker Desktop** (or Docker + Docker Compose v2)

---

## First-time installation

### 1. Install dependencies

```bash
# Python dependencies
uv sync --extra dev

# Frontend dependencies
cd frontend && npm ci && cd ..
```

### 2. Start the Docker infrastructure

```bash
docker compose up -d
```

This starts: Qdrant, Prefect server + services, Postgres (Prefect backend), Redis (Prefect messaging).

Wait ~60 seconds for the Prefect server to become healthy (http://localhost:4200).

### 3. Run one-time setup

```bash
uv run python scripts/setup.py
```

This creates the Prefect work pool (`battlemap-pool`) and registers all seven flow deployments (import pipeline, scheduled backups, staging cleanup, etc.).

**Only needs to run once per installation.** Re-run it if you reset the Prefect database or add new flows.

---

## Daily use

### Start

```bash
uv run python scripts/start.py
```

This starts Docker (if not already running), the Prefect worker, and the FastAPI server as background processes. Logs go to `logs/worker.log` and `logs/api.log`.

Then start the frontend in a second terminal:

```bash
cd frontend && npm run dev
```

| Service | URL |
|---|---|
| Gallery | http://localhost:5173 |
| API docs | http://localhost:8000/docs |
| Health check | http://localhost:8000/health |
| Prefect UI | http://localhost:4200 |

### Stop

```bash
uv run python scripts/stop.py
```

Leave Docker running for a faster restart next time:

```bash
uv run python scripts/stop.py --keep-docker
```

### Tail logs

```bash
tail -f logs/api.log       # FastAPI server
tail -f logs/worker.log    # Prefect worker (flow execution)
```

---

## Prefect deployments

All async processing runs through Prefect. Deployments are registered by `scripts/setup.py`.

| Deployment | Trigger | Purpose |
|---|---|---|
| `analyse-deployment` | Upload endpoint (sync) | Parse uploaded files, detect variant groups |
| `import-deployment` | Confirm endpoint (async) | Process a single variant group through the full pipeline |
| `import-job-deployment` | Confirm-all endpoint (async) | Process all groups in one run (CLIP loaded once) |
| `write-new-embeddings-deployment` | Manual (Prefect UI) | Backfill Qdrant with CLIP embeddings for existing images |
| `backfill-content-hash-deployment` | Manual (Prefect UI) | Compute SHA-256 hashes for existing images |
| `backup-deployment` | Scheduled — daily 03:00 UTC | SQLite snapshot + Qdrant snapshot + backup rotation |
| `cleanup-staging-deployment` | Scheduled — every 6 hours | Remove abandoned import staging directories |

Any deployment can be triggered manually from the Prefect UI at http://localhost:4200 → Deployments.

To re-register deployments after a change:

```bash
uv run python scripts/setup.py
```

---

## Configuration

Copy `.env.example` to `.env` and edit as needed:

```bash
cp .env.example .env
```

| Variable | Default | Description |
|---|---|---|
| `CORS_ORIGINS` | `["http://localhost:5173"]` | Add your LAN IP for remote access |
| `CLIP_DEVICE` | `cpu` | Set to `cuda` if a GPU is available |
| `MAX_IMPORT_FILE_SIZE` | `52428800` (50 MB) | Per-file upload limit |
| `MAX_IMPORT_TOTAL_SIZE` | `524288000` (500 MB) | Total upload size per import job |

---

## Database & backups

Schema is managed by **Alembic** (applied automatically on API startup):

```bash
uv run alembic upgrade head   # apply pending migrations manually
```

**Backups** run daily via Prefect and are written to `data/backups/{timestamp}/`:
- `battlemap.db` — consistent SQLite snapshot
- Qdrant snapshot — stored in Qdrant's own storage

Rotation keeps 7 daily + 4 weekly snapshots.

**Restore from backup:** copy `battlemap.db` from a backup directory to `data/battlemap.db`, then run `uv run alembic upgrade head`.

Image files in `data/store/` are not backed up by the script — the originals typically exist elsewhere. Qdrant embeddings can be regenerated with the `write-new-embeddings` deployment if needed.

---

## Development

### Running tests

```bash
# Unit tests (fast, no infrastructure needed)
uv run --extra dev python -m pytest backend/tests/unit/ -v

# Integration tests (self-contained, no Prefect server needed)
uv run --extra dev python -m pytest \
  backend/tests/integration/test_backup_restore.py \
  backend/tests/integration/test_upload_endpoint.py \
  backend/tests/integration/test_preview_endpoint.py \
  backend/tests/integration/test_confirm_endpoint.py \
  -v
```

### Linting

```bash
uv run ruff check backend/
uv run ruff format backend/
```

### Reset database (destructive)

```bash
uv run python reset_database.py
```

Drops and recreates the SQLite database. **All image metadata will be lost.** Image files in `data/store/` are not affected.

---

## Troubleshooting

**Prefect server not ready during setup:**
```bash
docker compose ps          # check all containers are Up
docker compose logs prefect-server --tail=50
```

**CLIP model slow to load:**
On first start, the CLIP model (~600 MB) downloads from HuggingFace. Subsequent starts use the local cache in `.cache/`.

**Import fails silently:**
Check the worker log — CLIP and PIL errors appear there, not in the API log:
```bash
tail -f logs/worker.log
```

**Qdrant not healthy:**
```bash
docker compose logs qdrant
curl http://localhost:6333/healthz
```
