# Scene Atlas

A tool for managing, searching, and exploring large collections of tabletop RPG scenes — battlemaps, vistas, portraits, and encounter art.

## Features

- **Hybrid search** — natural-language semantic search (CLIP) combined with keyword full-text search (FTS5 + Porter stemmer)
- **Tag-based filtering** — grid state, season, lighting, weather, terrain, and more; auto-extracted from filenames
- **Groups** — related images (different lighting, grid, weather variations) grouped automatically from name and folder structure
- **Web import** — drag-and-drop uploader with browser-side duplicate detection, ZIP support, and preview editing
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
- **Node.js 20+** with npm

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
uv run uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
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

By default, images are bind-mounted from `./images` in the project root.
To use a different directory, create a `.env` file:

```bash
cp .env.example .env
# Then edit .env:
IMAGE_DIR=/path/to/your/battlemaps
PORT=9000                          # change the host port (default 8000)
CORS_ORIGINS=["https://maps.example.com"]  # for reverse-proxy setups
```

App data (database, vector index, thumbnails) is stored in a named Docker
volume (`scene-atlas-data`). See `.env.example` for all available options.

---

## Development

### Start the dev servers

```bash
# Terminal 1: Backend
uv run python scripts/start.py

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
uv run python scripts/stop.py
```

### Tail logs

```bash
tail -f logs/api.log
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

GitHub Actions runs a tiered pipeline:

| Tier | Trigger | What runs |
|---|---|---|
| Lint + unit tests | Every push & PR | ruff, ESLint, Prettier, pytest unit, vitest, Vite build |
| Integration + coverage | Push to main | pytest integration, coverage reports (uploaded as artifacts) |
| Electron build | Version tags (`v*`) | Gate check → multi-platform build (Win/macOS/Linux) → GitHub Release |

Coverage thresholds: backend 40%, frontend 20% (ratcheted up over time).

For detailed test strategy, conventions, and stress testing, see [docs/testing.md](docs/testing.md).

---

## Configuration

Copy `.env.example` to `.env` and edit as needed:

```bash
cp .env.example .env
```

| Variable | Default | Description |
|---|---|---|
| `CORS_ORIGINS` | `["http://localhost:5173"]` | Add your LAN IP for remote access |
| `INFERENCE_DEVICE` | `auto` | GPU acceleration: `auto`/`cpu`/`cuda`/`directml`/`coreml` |
| `MAX_IMPORT_FILE_SIZE` | `52428800` (50 MB) | Per-file upload limit |
| `MAX_IMPORT_TOTAL_SIZE` | `524288000` (500 MB) | Total upload size per import job |

---

## Database & Backups

Schema is managed by **Alembic** (applied automatically on API startup):

```bash
uv run alembic upgrade head   # apply pending migrations manually
```

**Backups** run on a scheduled interval and are written to `data/backups/{timestamp}/`:
- `battlemap.db` — consistent SQLite snapshot
- Qdrant snapshot

Rotation keeps 7 daily + 4 weekly snapshots.

**Restore from backup:** copy `battlemap.db` from a backup directory to `data/battlemap.db`, then run `uv run alembic upgrade head`.

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
uv run python scripts/build_electron.py

# Or step by step
uv run python scripts/build_sidecar.py   # PyInstaller backend
cd frontend && npm run build              # Vite frontend
npm run electron:build                    # electron-builder
```

Release builds are automated via GitHub Actions on `v*` tags — push a tag like `v1.0.0` to trigger multi-platform builds and GitHub Release publishing.

---

## Troubleshooting

**CLIP model slow to load:**
On first start, an ONNX embedding model is downloaded from HuggingFace. Model sizes vary by selection: small ~250 MB, medium ~500 MB, large ~1 GB. Subsequent starts use the local cache.

**Import fails silently:**
Check the API log for errors:
```bash
tail -f logs/api.log
```

**Reset database (destructive):**
```bash
uv run python reset_database.py
```
Drops and recreates the SQLite database. All image metadata will be lost. Image files in `data/images/` are not affected.

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
- [design/decisions.md](design/decisions.md) — all architecture decision records (ADRs 001-017)
- [docs/building.md](docs/building.md) — build/deploy/run for all three deployment modes
- [docs/testing.md](docs/testing.md) — running tests, E2E setup, stress testing
