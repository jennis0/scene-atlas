# Building and Running Scene Atlas

Scene Atlas supports three deployment modes. All modes must build on Windows and Linux and run on Windows, Linux, and macOS.

## Developer Mode

### Prerequisites

- **Python 3.12+** with [uv](https://docs.astral.sh/uv/) for dependency management
- **Node.js 24+** with npm (root `package.json` `engines`)
- Python dependencies: `uv sync --extra dev --extra cpu` (a bare `uv sync` installs no ONNX Runtime; use `gpu`/`gpu-directml` instead of `cpu` for GPU inference, or `cpu-dev`/`gpu-dev` to add torch for model export)
- Root Node dependencies: `npm install` (installs the Husky git hooks)
- ONNX models: `uv run python scripts/models/setup_models.py` (downloads the embedding model from HuggingFace)

### Running Locally

```bash
# Terminal 1: Backend (FastAPI, port 8000)
uv run python scripts/app/start.py

# Terminal 2: Frontend (Vite dev server, port 5173, proxies /api -> :8000)
cd frontend && npm install && npm run dev
```

The frontend Vite config proxies `/api` requests to the backend at `localhost:8000` (`API_PROXY_TARGET` overrides it; E2E uses that). `scripts/app/start.py` supervises uvicorn with auto-restart and writes its output to `logs/api.log`; stop it with `uv run python scripts/app/stop.py`. The backend's own log is `data/logs/scene-atlas.log`.

### Pre-commit Hooks

Git hooks are auto-installed via `npm install` at the repo root (husky `prepare` script).

Pre-commit (lint-staged, fixes in place):
- `backend/**/*.py`, `scripts/**/*.py`: `ruff check --fix` + `ruff format`
- `frontend/src/**/*.{ts,tsx}`: `eslint --fix` + `prettier --write`
- `electron/src/**/*.ts`: `prettier --write`

Pre-push (`.husky/pre-push`, blocks the push on failure): `ruff check` and `ruff format --check` over `backend/` and `scripts/`, backend unit tests, ESLint, `prettier --check src/`, `tsc --noEmit` for the frontend and for `electron/`, and vitest.

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

For deployment behind a reverse proxy (e.g., nginx, Caddy). See [Docker Server](/deploy/server) and [Standalone Server](/deploy/standalone) for full guides.

```bash
# Build the frontend once; the backend serves frontend/dist automatically
cd frontend && npm run build && cd ..

# Run the backend (API + UI on one port)
uv run uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers
```

::: danger
Server mode has no built-in authentication. Run it only behind a reverse proxy that authenticates users (basic auth, forward-auth, or an OAuth proxy), never directly exposed to the internet.
:::

### Configuration

All config via environment variables or `.env` file. Key settings:

| Variable | Default | Purpose |
|----------|---------|---------|
| `APP_DATA_DIR` | `data/` | DB, LanceDB, thumbnails, staging, logs |
| `IMAGE_LIBRARY_DIR` | `images/`, or `<APP_DATA_DIR>/images` when only `APP_DATA_DIR` is set | Managed image store and `backups/` |
| `CORS_ORIGINS` | `["http://localhost:3000","http://localhost:5173","http://localhost:8000"]` | Allowed CORS origins (JSON array) |
| `APP_MODE` | `server` | `server`, or `app` when run as the Electron sidecar |

All other paths (database, vector index, thumbnails, staging, backups) are always derived from `APP_DATA_DIR` and `IMAGE_LIBRARY_DIR` in `backend/app/config.py`.

See the [Configuration Reference](/deploy/configuration) and `.env.example` for the full list.

### Reverse Proxy Notes

- The proxy should handle TLS termination
- Set `Strict-Transport-Security` header at the proxy level
- The proxy must authenticate users; Scene Atlas has no authentication of its own
- Configure `CORS_ORIGINS` to match your actual frontend domain
- The proxy should overwrite `X-Forwarded-For` so rate limits key on the real client IP

## Electron Desktop Build

### Development

```bash
# Vite dev server + Electron window (from the repo root)
npm run electron:dev
```

**WSL:** WSLg doesn't pass Windows' display scaling to Linux apps, so on a 4K screen the Linux build opens at 100% and looks tiny. Add `export GDK_SCALE=2` (or your Windows scale, rounded) to `~/.bashrc`, or use Settings → Appearance → Zoom.

### Production Build

**Tool:** electron-builder (`electron-builder.yml`)

**Build targets:**

| Platform | Format | Architectures |
|----------|--------|---------------|
| Windows | NSIS installer | x64 |
| macOS | DMG | arm64 (Apple Silicon) only |
| Linux | AppImage + DEB | x64 |

Each platform's installer must be built on that platform (the PyInstaller sidecar is not cross-compiled). The ONNX Runtime package is chosen by the `uv sync` extra: the Windows release build uses `gpu-directml` (DirectML), macOS and Linux use `cpu` (CoreML is built into the macOS package). There is one installer per platform; there is no separate GPU build.

**Sidecar bundling:** The Python backend is frozen via PyInstaller (`backend/pyinstaller/scene_atlas_backend.spec`) into a `--onedir` output. This is copied into `resources/sidecar/` via electron-builder's `extraResources`.

```bash
# Full build: sidecar + frontend + Electron installer for the current platform
uv run python scripts/build/build_electron.py

# Useful flags: --skip-sidecar, --skip-frontend, --clean, --no-package,
#               --dev (unpacked, no installer), --platform windows|macos|linux

# Or step by step
uv run python scripts/build/build_sidecar.py   # PyInstaller backend
cd frontend && npm run build && cd ..         # Vite frontend
npm run electron:build                        # tsc + electron-builder
```

**Publishing:** electron-builder publishes to GitHub Releases (`publish.provider: github`, channel `latest`) only when the release workflow runs with `publish=true`. The app has no built-in auto-updater.

### Config Storage

| Item | Location |
|------|----------|
| App config | `{userData}/scene-atlas-config.json` |
| Backend log | `{userData}/backend.log` |
| App data / image library dirs | Chosen during first launch (default `Documents/Scene Atlas/data` and `.../images`); passed to the sidecar as `--app-data-dir` / `--image-library-dir` |

`userData` is the OS-standard app data path (e.g. `%APPDATA%/Scene Atlas` on Windows, `~/Library/Application Support/Scene Atlas` on macOS, `~/.config/Scene Atlas` on Linux).

## CI/CD

Lint and unit tests run locally in the pre-push hook; CI does not repeat them on every push.

- `.github/workflows/ci.yml` (pull requests): pip-audit + bandit, backend unit + integration tests with coverage, frontend npm audit (runtime deps) + `tsc` + Vite build
- `.github/workflows/release.yml` (manual `workflow_dispatch`): backend lint/unit/integration/heavy tests, frontend lint/test/coverage/build, unit tests on Windows and macOS, Playwright E2E, then Electron builds for Windows x64, macOS arm64, and Linux x64. Run it against `main`, check the artifacts, then re-run with `publish=true` and a `version` to create the GitHub Release.
- `.github/workflows/docs.yml` (push to `main` touching `docs/`): builds this documentation site and deploys it to GitHub Pages if Pages is enabled

For details on running tests, see [testing.md](testing.md).
