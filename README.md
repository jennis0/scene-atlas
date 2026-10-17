# Scene Atlas

A self-hosted scene manager for tabletop RPG art. Search large collections of battlemaps, vistas, and encounter art by visual content.

## Features

- **Hybrid search** — natural-language semantic search (CLIP) combined with keyword full-text search (FTS5 + Porter stemmer)
- **Tag-based filtering** — grid state, season, lighting, weather, terrain, and more; auto-extracted from filenames
- **Groups** — related images (different lighting, grid, weather variations) grouped automatically from name and folder structure
- **Web import** — drag-and-drop files, folders, or ZIPs; browser-side duplicate detection; resumable uploads; server-side grouping
- **Color search** — filter by dominant colours extracted from each image
- **Grid detection** — automatic square and hex grid detection for battlemaps (filename-based + optional image analysis)
- **Type-aware processing** — per-image type selection (battlemap or scene); battlemaps get grid detection, scenes skip it
- **Desktop app** — Electron wrapper with bundled backend (PyInstaller sidecar)
- **100% local** — no cloud services; runs on your machine with no external dependencies

## Tech Stack

| Layer | Technology |
|---|---|
| Backend API | FastAPI + SQLAlchemy (SQLite) |
| Semantic search | CLIP / SigLIP2 (multi-model via ONNX Runtime) → LanceDB |
| Full-text search | SQLite FTS5 with Porter stemmer |
| Background jobs | In-process ThreadPoolExecutor + async scheduler |
| Frontend | React 18 + TypeScript + Vite + Tailwind + Radix UI |
| Desktop | Electron + PyInstaller sidecar |

---

## Prerequisites

- **Python 3.12+** with [uv](https://docs.astral.sh/uv/)
- **Node.js 24+** with npm

No Docker required — vector search runs in-process via LanceDB.

---

## First-time setup

```bash
# Python dependencies (dev tools + CPU onnxruntime)
uv sync --extra dev --extra cpu

# Frontend dependencies
cd frontend && npm ci && cd ..

# Root dependencies (for Electron dev / pre-commit hooks)
npm install
```

### Server deployment

For server deployments (no dev dependencies), you must explicitly install an onnxruntime variant:

```bash
uv sync --extra cpu                        # CPU-only inference
uv sync --extra gpu                        # NVIDIA GPU (requires CUDA toolkit + cuDNN)
uv sync --extra gpu-directml               # DirectX 12 GPU (Windows only)
```

For model export/re-quantization (requires torch), use the `-dev` variants instead:

```bash
uv sync --extra dev --extra cpu-dev        # CPU + dev tools + torch
uv sync --extra dev --extra gpu-dev        # CUDA + dev tools + torch
```

A bare `uv sync` does **not** install onnxruntime — the app will fail at startup with a clear error.

### Standalone server (no Docker)

Build the frontend once, then run the backend directly. The backend auto-detects
the built frontend and serves both the API and UI on a single port.

```bash
cd frontend && npm run build && cd ..
uv run uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --no-proxy-headers
```

Configure via `.env` — see `.env.example` for available options.

### Docker

The simplest way to deploy Scene Atlas as a server. The container builds the
frontend into the image and serves both the API and UI on a single port.

```bash
# CPU inference
docker compose --profile cpu up -d

# NVIDIA GPU inference (requires nvidia-container-toolkit)
docker compose --profile gpu up -d
```

By default, managed image storage is bind-mounted from `./images` in the project root.
This is where Scene Atlas writes imported files — do not point it at your existing
image collection. To change the host path, create a `.env` file:

```bash
cp .env.example .env
# Then edit .env:
IMAGE_DIR=/mnt/data/scene-atlas-images  # managed storage path
PORT=9000                               # change the host port (default 8000)
CORS_ORIGINS=["https://maps.example.com"]  # for reverse-proxy setups
```

App data (database, vector index, thumbnails) is stored in a named Docker
volume (`scene-atlas-data`). See `.env.example` for all available options.

---

## Development

### Start the dev servers

```bash
# Terminal 1: Backend
uv run python scripts/app/start.py

# Terminal 2: Frontend
cd frontend && npm run dev
```

| Service | URL |
|---|---|
| Gallery | http://localhost:5173 |
| API docs | http://localhost:8000/docs |
| Health check | http://localhost:8000/health |

### Stop the backend

```bash
uv run python scripts/app/stop.py
```

### Tail logs

```bash
tail -f logs/api.log              # stdout/stderr captured by scripts/app/start.py
tail -f data/logs/scene-atlas.log # backend's own rotating log (under APP_DATA_DIR)
```

---

## Testing & Quality

Pre-commit hooks run automatically on `git commit` via Husky + lint-staged (ruff for Python, ESLint + Prettier for TypeScript).

### Quick commands

```bash
make check          # lint + format check (backend + frontend)
make test           # unit tests + frontend tests (~15s)
make test-all       # + integration tests (~30s)
make test-cov       # full suite with coverage reporting
make lint-fix       # auto-fix all lint + format issues
```

### Individual commands

```bash
# Backend
uv run ruff check backend/                    # lint
uv run ruff format --check backend/           # format check
uv run python -m pytest backend/tests/unit -v # unit tests

# Frontend
cd frontend && npx eslint . --ext ts,tsx --max-warnings 0
cd frontend && npx prettier --check src/
cd frontend && npx vitest run
cd frontend && npm run build                  # TypeScript + Vite build
```

### CI/CD

| Stage | Trigger | What runs |
|---|---|---|
| Pre-push hook (`.husky/pre-push`) | `git push` (local) | ruff check + format check (`backend/`, `scripts/`), pytest unit, ESLint, Prettier, `tsc` (frontend + Electron), vitest |
| CI (`.github/workflows/ci.yml`) | Pull requests | pip-audit + bandit, backend unit + integration tests with coverage, frontend type check + build |
| Release (`.github/workflows/release.yml`) | Manual (`workflow_dispatch`) | Full tests, cross-platform unit tests, Playwright E2E, Electron builds; publishes a GitHub Release when run with `publish=true` |

Coverage thresholds: backend 40%, frontend 20% (ratcheted up over time).

For running tests, E2E setup, and stress testing, see [docs/development/testing.md](docs/development/testing.md).

---

## Configuration

Copy `.env.example` to `.env` and edit as needed:

```bash
cp .env.example .env
```

| Variable | Default | Description |
|---|---|---|
| `APP_DATA_DIR` | `./data` | Database, vector index, thumbnails, logs |
| `IMAGE_LIBRARY_DIR` | `./images`, or `<APP_DATA_DIR>/images` when only `APP_DATA_DIR` is set | Managed image store and backups |
| `CORS_ORIGINS` | `["http://localhost:3000","http://localhost:5173","http://localhost:8000"]` | JSON array; set to your domain behind a reverse proxy |
| `INFERENCE_DEVICE` | `auto` | GPU acceleration: `auto`/`cpu`/`cuda`/`directml`/`coreml` |

Full reference: [docs/deploy/configuration.md](docs/deploy/configuration.md).

Server mode has **no built-in authentication**. Expose it only behind a reverse proxy that authenticates users (basic auth, forward-auth, or an OAuth proxy), and never directly to the internet.

---

## Database & Backups

Schema is managed by **Alembic** (applied automatically on API startup):

```bash
uv run alembic upgrade head   # apply pending migrations manually
```

**Backups** run every 24 hours (when the scheduler is enabled) and are written to `<IMAGE_LIBRARY_DIR>/backups/{timestamp}/` (default `images/backups/`):
- `battlemap.db` — consistent SQLite snapshot
- LanceDB vector index snapshot

Rotation keeps the 7 most recent snapshots plus up to 4 older weekly ones.

**Restore from backup:** stop the backend, copy `battlemap.db` from a backup directory to `<APP_DATA_DIR>/battlemap.db` (default `data/battlemap.db`), then start it again; migrations run on startup.

---

## Electron Desktop App

### Dev mode

```bash
npm run electron:dev
```

Starts the Vite dev server and Electron concurrently.

### Build

```bash
# Full build (sidecar + frontend + Electron)
uv run python scripts/build/build_electron.py

# Or step by step
uv run python scripts/build/build_sidecar.py   # PyInstaller backend
cd frontend && npm run build              # Vite frontend
npm run electron:build                    # electron-builder
```

Release builds come from the manual `Release` workflow (`.github/workflows/release.yml`). Run it against `main` to test and build Windows (x64), macOS (Apple Silicon/arm64 only), and Linux (x64) artifacts; re-run with `publish=true` and a `version` to create the GitHub Release.

---

## Troubleshooting

**CLIP model slow to load:**
On first start, an ONNX embedding model is downloaded from HuggingFace. Model sizes vary by selection: small ~250 MB, medium ~500 MB, large ~1 GB. Subsequent starts use the local cache.

**Import fails silently:**
Open the import from the activity dock and view its report for per-file problems, then check the backend log:
```bash
tail -f data/logs/scene-atlas.log
```

**Start over with an empty library (destructive):**
Stop the backend, then delete `APP_DATA_DIR` (default `data/`: database, vector index, thumbnails) and `IMAGE_LIBRARY_DIR` (default `images/`: stored files and backups). Both are recreated on the next start. Stored files are content-addressed and cannot be used without the database, so delete both together.

---

## Documentation

| Directory | Contents |
|---|---|
| [design/](design/README.md) | Architecture, component design, decisions, visual standards, status and backlog |
| [docs/](docs/) | How to build, test, deploy, and operate the system (VitePress) |

To browse the docs locally:

```bash
cd docs && npm install && npm run dev
```

Key docs:
- [design/status-and-roadmap.md](design/status-and-roadmap.md) — feature inventory, in-progress work, backlog
- [design/decisions.md](design/decisions.md) — architecture decision records
- [docs/development/building.md](docs/development/building.md) — build/deploy/run for all three deployment modes
- [docs/development/testing.md](docs/development/testing.md) — running tests, E2E setup, stress testing
