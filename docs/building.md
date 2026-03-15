# Building and Running Scene Atlas

Scene Atlas supports three deployment modes. All modes must build on Windows and Linux and run on Windows, Linux, and macOS.

## Developer Mode

### Prerequisites

- **Python 3.12+** with [uv](https://docs.astral.sh/uv/) for dependency management
- **Node.js 18+** with npm
- ONNX models: `uv run python scripts/models/setup_models.py` (downloads CLIP model and quantises it)

### Running Locally

```bash
# Backend (FastAPI, port 8000)
uv run uvicorn backend.app.main:app --reload

# Frontend (Vite dev server, port 5173, proxies /api -> :8000)
cd frontend && npm install && npm run dev

# Both via Makefile
make dev
```

The frontend Vite config proxies `/api` requests to the backend at `localhost:8000`.

### Pre-commit Hooks

Pre-commit hooks are auto-installed via `npm install` (husky prepare script):
- Python: `ruff check` + `ruff format` on staged `.py` files
- Frontend: `eslint` + `prettier` on staged `.ts`/`.tsx` files

### Linting and Formatting

```bash
make check          # lint + format-check (both backend + frontend)
make lint-fix       # auto-fix all lint + format issues

# Individual
uv run ruff check backend/ --fix
uv run ruff format backend/
cd frontend && npx eslint src/ --fix && npx prettier --write src/
```

## Web Server Mode

For deployment behind a reverse proxy (e.g., nginx, Caddy).

```bash
# Production backend
uv run uvicorn backend.app.main:app --host 0.0.0.0 --port 8000

# Production frontend build
cd frontend && npm run build
# Serve dist/ via reverse proxy or static file server
```

### Configuration

All config via environment variables or `.env` file. Key settings:

| Variable | Default | Purpose |
|----------|---------|---------|
| `DATABASE_URL` | `sqlite:///./data/battlemap.db` | SQLite database path |
| `STORE_IMAGES_DIR` | `data/store/images` | Image storage directory |
| `STORE_THUMBNAILS_DIR` | `data/store/thumbnails` | Thumbnail storage directory |
| `STAGING_DIR` | `data/staging` | Import staging directory |
| `QDRANT_PATH` | `data/qdrant_local` | Qdrant embedded storage |
| `AUTH_TOKEN` | (unset) | Optional bearer token for API auth |
| `CORS_ORIGINS` | `localhost:3000,5173,8000` | Allowed CORS origins |
| `APP_MODE` | `auto` | Force mode: `server`, `electron`, `auto` |

See `.env.example` for the full list.

### Reverse Proxy Notes

- The proxy should handle TLS termination
- Set `Strict-Transport-Security` header at the proxy level
- Configure `CORS_ORIGINS` to match your actual frontend domain
- If `AUTH_TOKEN` is set, all API requests require `Authorization: Bearer <token>`

## Electron Desktop Build

### Development

```bash
# Start the backend sidecar + Electron window
cd electron && npm run dev
```

### Production Build

**Tool:** electron-builder (`electron-builder.yml`)

**Build targets:**

| Platform | Format | Architectures |
|----------|--------|---------------|
| Windows | NSIS installer | x64 |
| macOS | DMG | x64 + arm64 |
| Linux | AppImage + DEB | x64 |

**Sidecar bundling:** The Python backend is frozen via PyInstaller (`backend/pyinstaller/scene-atlas-backend.spec`) into a `--onedir` output. This is copied into `resources/sidecar/` via electron-builder's `extraResources`.

```bash
# Freeze the Python backend
cd backend/pyinstaller && uv run pyinstaller scene-atlas-backend.spec

# Build Electron distributable
cd electron && npm run build
```

**Auto-updates:** Configured to publish to GitHub Releases (`publish.provider: github`).

### Config Storage

| Item | Location |
|------|----------|
| App config | `{userData}/scene-atlas-config.json` |
| Backend log | `{userData}/backend.log` |
| Default data dir | `{Documents}/Scene Atlas/data` |

`userData` is the OS-standard app data path (e.g. `%APPDATA%/Scene Atlas` on Windows, `~/Library/Application Support/Scene Atlas` on macOS, `~/.config/Scene Atlas` on Linux).

## CI/CD

- `.github/workflows/ci.yml` -- Backend lint, unit tests, integration tests, heavy tests, E2E, frontend lint/test/build/coverage
- `.github/workflows/electron-build.yml` -- Gate check + matrix build for Windows/macOS/Linux on version tags

For details on running tests, see [testing.md](testing.md).
