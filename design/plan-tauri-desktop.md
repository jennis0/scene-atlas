# Plan: Bundle Scene Atlas as a Tauri v2 Desktop App

**Status**: Planned (not yet started)
**Created**: 2026-02-23

## Context

Scene Atlas currently runs as a FastAPI backend + React frontend started via terminal commands (`uv run uvicorn ...` + `npm run dev`). To distribute to non-technical users, we want to package it as a native desktop app using Tauri v2 with the Python backend as a PyInstaller-frozen sidecar binary. The existing dev workflow (`uv` + `npm`) must continue to work — Tauri is an additive packaging option.

**Targets**: Windows x86_64, macOS x86_64 + aarch64, Linux x86_64
**CLIP model**: Download on first launch (~600MB from HuggingFace), not bundled
**Expected installer size**: ~300-500MB (without CLIP weights)

---

## Architecture

```
Dev mode (unchanged):
  Terminal 1: uv run uvicorn backend.app.main:app --port 8000
  Terminal 2: cd frontend && npm run dev  (Vite :5173, proxies /api -> :8000)

Tauri dev mode:
  npm run tauri dev
    -> Tauri spawns Vite dev server + Python sidecar on a free port
    -> Webview loads http://localhost:5173

Tauri production:
  User launches Scene Atlas.exe/.app
    -> Tauri shows loading screen
    -> Rust spawns frozen Python sidecar: --port <free> --data-dir <appdata>
    -> Backend prints "SCENE_ATLAS_READY port=XXXXX" to stdout
    -> Rust reads port, emits "backend-ready" Tauri event with port
    -> Frontend listens for event, stores port, unblocks rendering
    -> Loading screen dismissed when /health returns 200
```

### Data Directory

| Mode | Location |
|------|----------|
| Dev (no Tauri) | `<project>/data/` (unchanged) |
| Tauri dev | `<project>/data/` |
| Tauri production | Platform app data dir via `--data-dir` |

Production paths: `%LOCALAPPDATA%/com.sceneatlas.app/data` (Win), `~/Library/Application Support/com.sceneatlas.app/data` (mac), `~/.local/share/com.sceneatlas.app/data` (Linux)

---

## Implementation Phases

### Phase 1: Backend Preparation (no Tauri dependency)

**1a. `backend/app/config.py`** — Derived path recomputation

The current code computes `store_images_dir`, `staging_dir`, etc. from `data_dir` at class definition time. If `DATA_DIR` is overridden via env var, the derived paths don't update. Fix in `__init__`:

```python
def __init__(self, **kwargs):
    super().__init__(**kwargs)
    # Recompute derived paths if data_dir was overridden
    default_data = Path(__file__).parent.parent.parent / "data"
    if self.data_dir != default_data:
        self.store_images_dir = self.data_dir / "store" / "images"
        self.store_thumbnails_dir = self.data_dir / "store" / "thumbnails"
        self.staging_dir = self.data_dir / "staging"
        self.qdrant_path = self.data_dir / "qdrant_local"
        self.database_url = f"sqlite:///{self.data_dir / 'battlemap.db'}"
    # Existing directory creation stays
    ...
```

Also add Tauri CORS origins (safe to add unconditionally):
```python
cors_origins: list[str] = [
    "http://localhost:3000", "http://localhost:5173",
    "tauri://localhost", "https://tauri.localhost",
]
```

**1b. `backend/app/main.py`** — CLI args + ready signal

Add to `if __name__ == "__main__":` block:
```python
import argparse, os
parser = argparse.ArgumentParser()
parser.add_argument("--port", type=int, default=None)
parser.add_argument("--data-dir", type=str, default=None)
args = parser.parse_args()
if args.data_dir:
    os.environ["DATA_DIR"] = args.data_dir
if args.port:
    os.environ["API_PORT"] = str(args.port)
```

Add ready signal at end of lifespan startup (after "Server ready" log):
```python
print(f"SCENE_ATLAS_READY port={settings.api_port}", flush=True)
```

Bind to `127.0.0.1` in sidecar mode (not `0.0.0.0`) for security.

**1c. New `backend/pyinstaller/entry.py`** — Frozen entry point

Sets env vars BEFORE any `backend.app.*` imports (critical — importing config.py constructs Settings immediately):
```python
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--data-dir", type=str, required=True)
    args = parser.parse_args()
    os.environ["DATA_DIR"] = args.data_dir
    os.environ["API_PORT"] = str(args.port)
    os.environ["API_HOST"] = "127.0.0.1"
    import uvicorn
    uvicorn.run("backend.app.main:app", host="127.0.0.1", port=args.port)
```

**Verify**: `uv run python -m backend.app.main --port 9000 --data-dir /tmp/test` works AND existing `uv run uvicorn backend.app.main:app` still works.

---

### Phase 2: Frontend URL Abstraction (no Tauri dependency)

**2a. New `frontend/src/lib/apiBase.ts`** — Dynamic base URL resolution

```typescript
export function getApiBaseUrl(): string {
  const port = (window as any).__SCENE_ATLAS_PORT__
  return port ? `http://localhost:${port}/api/v1` : '/api/v1'
}

export function resolveApiUrl(path: string): string {
  const port = (window as any).__SCENE_ATLAS_PORT__
  return port ? `http://localhost:${port}${path}` : path
}
```

**2b. Modify `frontend/src/lib/api.ts`** — Interceptor pattern

Replace static `baseURL: '/api/v1'` with a request interceptor that calls `getApiBaseUrl()` at request time (not import time — the port isn't known yet at import). Update the four URL helper functions (`getThumbnailUrl`, etc.) to use `resolveApiUrl()`.

**2c. Fix hardcoded `/api/v1/...` paths** in `useImportUpload.ts` and import `FileCard.tsx` — wrap with `resolveApiUrl()`.

**2d. New `frontend/src/components/TauriGate.tsx`** — Backend readiness gate

- In non-Tauri mode: renders children immediately (zero overhead)
- In Tauri mode (`window.__TAURI_INTERNALS__` exists): listens for `backend-ready` Tauri event carrying the port number, then polls `/health` every 1.5s until 200. Shows `<LoadingScreen />` until ready.

**2e. New `frontend/src/components/LoadingScreen.tsx`** — Branded splash screen

Spinner + "Starting Scene Atlas..." status text.

**2f. Modify `frontend/src/main.tsx`** — Wrap `<App>` with `<TauriGate>`

**Verify**: `npm run dev` + manual backend still works identically. Run `npx vitest run`.

---

### Phase 3: Tauri Scaffolding

**3a. Create `src-tauri/` at project root:**

```
src-tauri/
+-- Cargo.toml           (tauri 2, tauri-plugin-shell 2, portpicker, dirs)
+-- tauri.conf.json      (see below)
+-- build.rs             (standard tauri-build)
+-- capabilities/
|   +-- default.json     (shell:allow-spawn for sidecar)
+-- src/
|   +-- main.rs          (sidecar lifecycle)
+-- binaries/
|   +-- .gitkeep         (actual binaries gitignored)
+-- icons/               (generated from source PNG)
```

**3b. `src-tauri/tauri.conf.json`** key settings:
- `build.beforeDevCommand`: `cd ../frontend && npm run dev`
- `build.devUrl`: `http://localhost:5173`
- `build.frontendDist`: `../frontend/dist`
- `bundle.externalBin`: `["binaries/scene-atlas-backend"]`
- CSP: allow `connect-src http://localhost:*`, `img-src http://localhost:* blob: data:`

**3c. `src-tauri/src/main.rs`** — Sidecar lifecycle:
1. Pick free port via `portpicker`
2. Resolve data dir (dev: `./data`, prod: platform app data)
3. Spawn sidecar with `--port` and `--data-dir` args
4. Watch stdout for `SCENE_ATLAS_READY` line
5. Emit `backend-ready` Tauri event with port — frontend's TauriGate listens for this and sets `window.__SCENE_ATLAS_PORT__`
6. Kill sidecar on window close

**3d. Add to `frontend/package.json`:**
- devDependencies: `@tauri-apps/cli`, `@tauri-apps/api`, `@tauri-apps/plugin-shell`
- scripts: `"tauri": "tauri"`, `"tauri:dev": "tauri dev"`, `"tauri:build": "tauri build"`

**3e. Update `.gitignore`**: add `src-tauri/binaries/*`, `!src-tauri/binaries/.gitkeep`, `src-tauri/target/`

**Verify**: `npm run tauri dev` opens webview.

---

### Phase 4: PyInstaller Packaging

**4a. `backend/pyinstaller/scene_atlas_backend.spec`**

- Mode: `--onedir` (not `--onefile` — faster startup, no temp extraction, better AV compat)
- Entry: `backend/pyinstaller/entry.py`
- `console=True` (required for stdout ready signal)
- Hidden imports: torch, transformers, qdrant_client, cv2, sklearn, scipy, uvicorn internals, sqlalchemy.dialects.sqlite
- Excludes: tkinter, matplotlib, jupyter, pytest, ruff
- `--collect-all torch`, `--collect-submodules transformers`
- `upx=False` (causes issues with torch/opencv native libs)

**Gotchas:**
- Use CPU-only torch wheel (~300MB vs ~2GB with CUDA)
- qdrant-client embedded mode has C++ native libs that must be explicitly bundled
- Switch to `opencv-python-headless` for frozen builds (no GUI deps)

**4b. New `scripts/build_sidecar.py`**

1. Detect platform -> target triple (`x86_64-pc-windows-msvc`, `aarch64-apple-darwin`, etc.)
2. Run PyInstaller with the spec file
3. Copy `--onedir` output to `src-tauri/binaries/`
4. Rename main executable with target triple suffix (Tauri convention)

**Verify**: Build sidecar, run standalone with `--port` and `--data-dir`, verify `/health` returns 200.

---

### Phase 5: Full Build + CI/CD

**5a. Build commands:**
```bash
uv run python scripts/build_sidecar.py   # PyInstaller -> src-tauri/binaries/
cd frontend && npm run tauri build        # Frontend + Tauri bundle -> installer
```

**5b. `.github/workflows/tauri-build.yml`** — Matrix of 4 jobs:

| Runner | Target |
|--------|--------|
| `windows-latest` | `x86_64-pc-windows-msvc` |
| `macos-latest` | `aarch64-apple-darwin` (Apple Silicon) |
| `macos-13` | `x86_64-apple-darwin` (Intel) |
| `ubuntu-22.04` | `x86_64-unknown-linux-gnu` |

Each job: install Rust + Node + Python/uv + system deps -> build sidecar -> `tauri build` -> upload artifact.

Trigger: version tags (`v*`) or manual dispatch.

**macOS note**: Separate downloads for Intel/ARM initially. Universal binary is a future enhancement.

---

## Files Summary

| File | Action | Phase |
|------|--------|-------|
| `backend/app/config.py` | Modify: derived path recomputation, Tauri CORS | 1 |
| `backend/app/main.py` | Modify: CLI args, ready signal | 1 |
| `backend/pyinstaller/entry.py` | **New**: frozen entry point | 1 |
| `frontend/src/lib/apiBase.ts` | **New**: `getApiBaseUrl()`, `resolveApiUrl()` | 2 |
| `frontend/src/lib/api.ts` | Modify: interceptor, URL helpers | 2 |
| `frontend/src/components/TauriGate.tsx` | **New**: backend readiness gate | 2 |
| `frontend/src/components/LoadingScreen.tsx` | **New**: splash screen | 2 |
| `frontend/src/main.tsx` | Modify: wrap with TauriGate | 2 |
| `src-tauri/` (entire directory) | **New**: Tauri Rust project | 3 |
| `frontend/package.json` | Modify: Tauri deps + scripts | 3 |
| `backend/pyinstaller/scene_atlas_backend.spec` | **New**: PyInstaller config | 4 |
| `scripts/build_sidecar.py` | **New**: build automation | 4 |
| `.github/workflows/tauri-build.yml` | **New**: CI/CD pipeline | 5 |
| `.gitignore` | Modify: Tauri artifacts | 3 |

## Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| PyInstaller + torch fragility | **High** | `--collect-all torch`, CPU-only wheels, test on clean machines |
| Qdrant native libs not bundled | Medium | Explicit verification in build, test create/search from frozen binary |
| Port injection timing race | Medium | TauriGate blocks rendering, interceptor resolves lazily |
| Windows AV flagging PyInstaller exe | Medium | Code-signing certificate for production releases |
| CSP blocking localhost connections | Low | Explicit CSP in tauri.conf.json |

## Verification

1. **Dev workflow preserved**: `uv run uvicorn ...` + `npm run dev` still works identically
2. **Backend CLI args**: `python -m backend.app.main --port 9000 --data-dir /tmp/test` starts correctly
3. **Frontend unit tests**: `npx vitest run` all pass
4. **Backend unit tests**: `uv run pytest` all pass
5. **Tauri dev**: `npm run tauri dev` opens webview, backend starts on dynamic port
6. **Tauri build**: installer produced, app launches, sidecar starts and serves images
7. **First-run**: CLIP model downloads with loading screen shown
8. **Sidecar lifecycle**: closing window kills the Python process (no orphans)
