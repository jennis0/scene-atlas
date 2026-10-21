# Building and Running Scene Atlas

Scene Atlas supports three deployment modes. All modes must build on Windows and Linux and run on Windows, Linux, and macOS.

## Developer Mode

### Prerequisites

- **Python 3.12+** with [uv](https://docs.astral.sh/uv/) for dependency management
- **Node.js 24+** with npm (root `package.json` `engines`)
- Python dependencies: `uv sync --extra dev --extra cpu` (a bare `uv sync` installs no ONNX Runtime; use `gpu`/`gpu-directml` instead of `cpu` for GPU inference)
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

### Git Hooks

Husky installs the hooks when you run `npm install` at the repo root (the `prepare` script).

**Pre-commit** (`.husky/pre-commit` runs lint-staged, configured in the root `package.json`; fixes staged files in place):
- `backend/**/*.py`, `scripts/**/*.py`: `ruff check --fix` + `ruff format`
- `frontend/src/**/*.{ts,tsx}`: `eslint --fix` + `prettier --write`
- `electron/src/**/*.ts`: `prettier --write`

**Pre-push** (`.husky/pre-push`, blocks the push on the first failure):

| Area | Checks |
|------|--------|
| Backend | `ruff check` and `ruff format --check` over the git-tracked files in `backend/` and `scripts/`, pyright (pinned version, via `uvx`), backend unit tests |
| Frontend | ESLint (no warnings allowed), `prettier --check src/`, `tsc --noEmit`, knip (unused files, exports and dependencies), Vitest |
| Electron | `tsc --noEmit` on `electron/tsconfig.json`, `npm run test:electron` (Electron and upgrade-test unit tests, `node --test`) |
| Repo | jscpd duplication check (threshold in `.jscpd.json`) |

::: warning Fresh clones and worktrees
Each clone or worktree needs its own setup before the pre-push hook works: `uv sync --extra dev --extra cpu`, `npm install` at the root, and `npm ci` in `frontend/`. Without the synced venv, `uv run ruff` can fall through to a different ruff on your `PATH`, and pyright can't resolve `onnxruntime`.
:::

### Linting and Formatting

```bash
make check          # lint + format-check (both backend + frontend)
make lint-fix       # auto-fix all lint + format issues

# Individual
uv run ruff check backend/ --fix
uv run ruff format backend/
cd frontend && npx eslint src/ --fix && npx prettier --write src/
```

## Production-like Build

To run the app as a server deployment does (one port, no Vite), build the frontend once; the backend serves `frontend/dist` itself:

```bash
cd frontend && npm run build && cd ..
uv run uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers
```

Open `http://localhost:8000`. Rebuild the frontend after frontend changes. Environment variables and `.env` work as in a real deployment; see `.env.example`.

For deploying it, see [Standalone Server](/deploy/standalone), [Docker Server](/deploy/server) (including reverse proxy and authentication) and the [Configuration Reference](/deploy/configuration).

## Electron Desktop Build

### Development

```bash
# Vite dev server + Electron window (from the repo root)
npm run electron:dev
```

In development Electron loads the Vite dev server and starts no backend of its own: run `uv run python scripts/app/start.py` alongside it. F12 or Ctrl+Shift+I toggles DevTools.

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

**Publishing and updates:** builds run with `--publish never`; the `publish` block in `electron-builder.yml` only makes electron-builder write the update metadata (`latest*.yml`, blockmaps), which the Release workflow uploads with the installers. The app updates itself with electron-updater: Windows and AppImage installs download and install, macOS and `.deb` installs only notify. See [design/electron.md](https://github.com/jennis0/scene-atlas/blob/main/design/electron.md#updates).

### Config Storage

| Item | Location |
|------|----------|
| App config | `{userData}/scene-atlas-config.json` |
| Backend log | `{userData}/backend.log` (rotated to `backend.log.1`) |
| Updater log | `{userData}/updater.log` |
| App data / image library dirs | A first launch writes the defaults (`%LOCALAPPDATA%\Scene Atlas\data` and `...\images` on Windows, `Documents/Scene Atlas/...` elsewhere) as a provisional library; the setup wizard's library step can replace them. Passed to the sidecar as `--app-data-dir` / `--image-library-dir` |
| Linked folder (`linkedLibraryDir`) | Optional: the user's own images folder, read in place. Chosen in the setup wizard or Settings; passed as `--linked-library-dir`. In `npm run electron:dev` the folders are only saved to the config: the dev backend ignores them (set `APP_DATA_DIR`, `IMAGE_LIBRARY_DIR`, `LINKED_LIBRARY_DIR` for it) |

The config also holds the update choice, window state and display preferences; see [design/electron.md](https://github.com/jennis0/scene-atlas/blob/main/design/electron.md#config-storage) for the full shape.

`userData` is the OS-standard app data path (e.g. `%APPDATA%/Scene Atlas` on Windows, `~/Library/Application Support/Scene Atlas` on macOS, `~/.config/Scene Atlas` on Linux).

## CI/CD

Lint and unit tests run locally in the pre-push hook. CI runs only on pull requests and manual runs; nothing runs on a push to a branch.

- `.github/workflows/ci.yml` (pull requests to `main`): pip-audit + bandit; backend unit and integration tests with coverage (small ONNX model, cached); frontend `npm audit` (runtime deps, high+) and `npm run build` (`tsc` + Vite); pyright, knip and jscpd.
- `.github/workflows/release.yml` (manual): checks the version, runs the full backend, frontend and cross-platform (Windows, macOS) tests and Playwright E2E, builds the Electron installers (Windows x64, macOS arm64, Linux x64) and builds and smoke-tests the Docker image. Without `publish=true` it stops there, as a check of `main`.
- `.github/workflows/release-published.yml` (a release is published): tags the Docker image `sha-<commit>` with the version and, unless it's a prerelease, `latest`.
- `.github/workflows/docs.yml` (push to `main` touching `docs/`, or manual): builds this site and deploys it to GitHub Pages, if Pages is enabled.

### Releasing

1. Bump the version in a PR: `python scripts/release/release_version.py bump X.Y.Z`, then merge it.
2. Run the Release workflow against `main` with `publish=true`. It creates a draft release `vX.Y.Z` from its own builds and pushes the Docker image as `sha-<commit>`. Installed apps ignore drafts.
3. Check the draft's installers, then publish it on GitHub. That tags the Docker image (`release-published.yml`).

Details are in [design/releasing.md](https://github.com/jennis0/scene-atlas/blob/main/design/releasing.md).

For running tests, see [Testing](testing.md).
