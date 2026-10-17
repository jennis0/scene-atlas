# Electron Desktop App

Scene Atlas ships as a desktop app using Electron (44; it needs macOS 13+, and the binary is downloaded on first run rather than by an npm `postinstall`). The Electron shell handles windowing and native OS integration while the Python backend runs as a sidecar subprocess.

## Architecture

```
┌──────────────────────────────────────────────────┐
│  Electron Main Process  (electron/src/main.ts)   │
│  ┌────────────────┐  ┌────────────────────────┐  │
│  │  Setup Window   │  │  Main Window            │  │
│  │  (first-run)    │  │  React app              │  │
│  │  setup.html     │  │                         │  │
│  │  ↕ setup IPC    │  │  ↕ preload IPC          │  │
│  └────────────────┘  └────────────────────────┘  │
│                            │                      │
│                      ┌─────▼──────┐               │
│                      │  Sidecar   │               │
│                      │  (Python   │               │
│                      │  backend)  │               │
│                      └────────────┘               │
└──────────────────────────────────────────────────┘
```

- **Main process** — Window lifecycle, IPC handlers, sidecar management. Holds a single-instance lock; a second launch focuses the existing window.
- **Preload scripts** — Secure IPC bridges (context-isolated, sandboxed, no Node integration)
- **Renderer** — The React frontend. Packaged, it is served by the sidecar at `http://127.0.0.1:<port>/`; in dev, by Vite at `localhost:5173`
- **Sidecar** — PyInstaller-frozen Python backend (FastAPI + Uvicorn), spawned as a child process

### How the UI is loaded

The sidecar bundles `frontend/dist` (PyInstaller datas) and serves it like server mode does, so the
packaged UI and the API share one origin. There is no CORS configuration, no port injection, and the
UI's CSP is just `connect-src 'self'`. (Loading the UI from `file://` would send `Origin: null`, which
the backend's CORS correctly rejects.)

While the backend starts, the window shows `electron/loading.html`, a dependency-free page that
renders `backend-error` messages. Once `/health` answers, main navigates the window to the sidecar
origin. If the backend dies later, main sends the window back to `loading.html` with the error.

The sidecar prefers port **47816** and falls back to any free port. A stable port keeps the UI's
origin, and therefore its localStorage (theme, custom colours, view preferences), the same across launches.

## Startup Sequence

```
app.whenReady()  (only if the single-instance lock was acquired)
  → loadConfig()
  → config exists?
     ├── YES → launchApp(appDataDir, imageLibraryDir, convertToWebp)
     │         → createMainWindow()
     │         → isDev?
     │         │   ├── YES → load the Vite dev server (developer runs the backend on port 8000)
     │         │   └── NO  → load loading.html
     │         │              → prepareStorageDirs()  (create + write-test both roots; error page if unusable)
     │         │              → findFreePort(47816)
     │         │              → spawnSidecar(port, appDataDir, imageLibraryDir, convertToWebp)
     │         │              → sidecar prints SCENE_ATLAS_READY (once uvicorn is listening)
     │         │              → poll /health → loadURL(http://127.0.0.1:<port>/)
     │         └── App.tsx checks /models/setup-status → ModelSetupScreen or gallery
     └── NO  → showSetupWindow()
              → user picks appDataDir, imageLibraryDir, convertToWebp
              → setup:complete IPC → validate + prepareStorageDirs → saveConfig → launchApp(...)
```

The main process remembers the last `backend-error` and re-sends it on every `did-finish-load`, and the preload caches it, so the loading page receives it even after a reload.

The Electron setup window only chooses storage directories. Model and tag-pack setup runs in the UI (`App.tsx` → `ModelSetupScreen`) in every mode, desktop included (see [hf-model-management.md](hf-model-management.md#first-boot-experience)).

## IPC Channels

Every handler is registered through `handleTrusted()`, which rejects calls whose sender frame is not an app URL (`isAppUrl()` in `main.ts`). Windows are hardened: `window.open` is denied and navigation away from the app is blocked; http(s) links open in the system browser.

### Setup Window (via `setupAPI`, `electron/src/setup.preload.ts`)

| Channel | Direction | Purpose |
|---------|-----------|---------|
| `setup:get-default-dirs` | renderer → main | Returns `{ appDataDir, imageLibraryDir }` defaults (`Documents/Scene Atlas/data` and `Documents/Scene Atlas/images`) |
| `setup:choose-directory` | renderer → main | Opens native folder picker, returns single selected path |
| `setup:complete` | renderer → main | Validates absolute paths, creates and write-tests both roots, saves config, launches app, closes setup. Returns `{ error: string \| null }` |

### Main Window (via `electronAPI`, `electron/src/preload.ts`)

| Channel | Direction | Purpose |
|---------|-----------|---------|
| `backend-error` | main → loading page | Error message if the sidecar fails to start or crashes |
| `system:get-app-data-dir` | renderer → main | Returns current app data directory path |
| `system:get-image-library-dir` | renderer → main | Returns current image library directory path |
| `system:choose-app-data-dir` | renderer → main | Opens native folder picker for new app data location |
| `system:choose-image-library-dir` | renderer → main | Opens native folder picker for new image library location |
| `system:change-storage-dirs` | renderer → main | Validates and prepares the new roots, saves config, stops the sidecar, relaunches the app. Resolves with `{ error }` only if the new locations are rejected |

### Preload API Surface

```typescript
window.electronAPI = {
  platform: string,                                   // 'darwin' | 'win32' | 'linux'
  onBackendError: (cb: (msg) => void) => () => void,  // replays cached value; used by loading.html
  getAppDataDir: () => Promise<string | null>,
  getImageLibraryDir: () => Promise<string | null>,
  chooseAppDataDir: () => Promise<string | null>,
  chooseImageLibraryDir: () => Promise<string | null>,
  changeStorageDirs: (appDataDir, imageLibraryDir) => Promise<{ error: string | null }>,
}
```

File and folder imports use standard browser APIs in the renderer; there is no filesystem IPC.

## Sidecar Lifecycle

1. **Port discovery** — `findFreePort(47816)` uses the preferred port if free, otherwise binds `127.0.0.1:0` for an OS-assigned port
2. **Spawn** — `spawn(sidecarPath, ['--port', port, '--app-data-dir', appDataDir, '--image-library-dir', imageLibraryDir, '--parent-pid', process.pid], { env: { ...process.env, CONVERT_TO_WEBP: '1' | '0' } })`, stdin/stdout/stderr piped (stdin is never written to; see the parent watchdog below). Sidecar path: `path.join(process.resourcesPath, 'sidecar', 'scene-atlas-backend[.exe]')`. `CONVERT_TO_WEBP=1` only seeds the `stored_format` app setting to `webp` on first boot (otherwise `original`); after that, Settings → Stored format is authoritative.
3. **Ready signal** — `entry.py` runs uvicorn through a `uvicorn.Server` subclass that prints `SCENE_ATLAS_READY port=…` after startup has bound the socket (so after the lifespan, too). The main process scans stdout for it, polls `/health`, then loads the UI from the sidecar. Only the sidecar prints the marker; other launchers (E2E, the stress runner) poll `/health`
4. **Logging** — stdout/stderr appended to `{userData}/backend.log`; the log is rotated to `backend.log.1` when it exceeds 5 MB at startup
5. **Failure handling** — Spawn errors, any exit before ready, and a non-zero exit after ready send `backend-error` with the last 10 output lines and the log path. `loading.html` headlines the last Python exception message in those lines (e.g. another backend already holding the data folder's lock, see [backend.md](backend.md#startup-sequence-mainpy-lifespan)), else the first line of the error
6. **Shutdown** — `stopSidecar()` closes the sidecar's stdin and, except on Windows, sends `SIGTERM`, then waits up to 5 s; on Windows, where `kill()` is `TerminateProcess`, it kills the sidecar only if it is still running after that. Called on `window-all-closed`, `will-quit`, and before relaunching for a storage change
7. **Parent watchdog** — `--parent-pid` turns on `backend/app/parent_watchdog.py` in the sidecar, so it never outlives Electron (crash, force-quit, `app.exit()` without `will-quit`). It fires when stdin reaches EOF (the OS closes Electron's end of the pipe however Electron exits, on every platform) or when a 2 s poll finds the parent PID gone (psutil, so a reused PID doesn't count; covers an unreadable stdin). Firing sets the uvicorn server's `should_exit`, which runs the normal graceful shutdown (ingest batch, storage locks); if the process is still alive 90 s later it calls `os._exit(1)`. Without the flag (dev, server mode) stdin is ignored

In dev mode the sidecar is not spawned — the developer runs the backend on port 8000.

## Borderless Window

Uses platform-specific titlebar:
- **macOS:** `titleBarStyle: 'hiddenInset'` (native traffic lights)
- **Windows/Linux:** `titleBarStyle: 'hidden'` with `titleBarOverlay` (system buttons drawn by Electron: `#0e1118` background, `#ede8dc` symbols, 32px high)

The frontend reserves top padding for the window controls drag region.

## Build & Packaging

**Tools:** PyInstaller (`backend/pyinstaller/scene_atlas_backend.spec`, driven by `scripts/build/build_sidecar.py`) and electron-builder (`electron-builder.yml`, driven by `scripts/build/build_electron.py`). Release builds run in the `build` matrix of `.github/workflows/release.yml` (see [testing.md](testing.md#where-checks-run)).

**Targets:**
| Platform | Format | Architectures |
|----------|--------|---------------|
| Windows | NSIS installer | x64 |
| macOS | DMG | arm64 (Apple Silicon only) |
| Linux | AppImage + DEB | x64 |

macOS is built only on the arm64 runner; there is no Intel or universal build.

**Sidecar bundling:** The PyInstaller `--onedir` output (`backend/pyinstaller/dist/scene-atlas-backend/`) is copied into `resources/sidecar/` via `extraResources`.

**Models:** ONNX models are not bundled. They are downloaded from Hugging Face at runtime by `model_download_service`; first launch therefore needs an internet connection (see [hf-model-management.md](hf-model-management.md)).

### GPU support in desktop builds

There is one build per platform; GPU support comes from the onnxruntime package installed at build time, selected by the release matrix `ort_extra` value (`uv sync --extra dev --extra <ort_extra>`):

| Platform | `ort_extra` | ORT package | GPU provider |
|----------|-------------|-------------|--------------|
| Windows | `gpu-directml` | `onnxruntime-directml` | DirectML (any DirectX 12 GPU) |
| macOS | `cpu` | `onnxruntime` | CoreML (built into the macOS wheel) |
| Linux | `cpu` | `onnxruntime` | none (CPU only) |

The PyInstaller spec keeps onnxruntime's `entry_points.txt` (DirectML plugin registration) (DirectML plugin registration). UPX is off: it corrupted bundled shared libraries (numpy's OpenBLAS), slows startup and trips Windows antivirus. At runtime `ort_providers.py` resolves the provider and falls back to CPU (see [gpu-acceleration.md](gpu-acceleration.md)).

**Auto-updates:** electron-builder publishes to GitHub Releases (`publish.provider: github`) on the single `latest` channel for all platforms.

## Config Storage

| Item | Location |
|------|----------|
| App config | `{userData}/scene-atlas-config.json` — `{ appDataDir, imageLibraryDir, convertToWebp }` (`convertToWebp` defaults to `false` if absent) |
| Backend log | `{userData}/backend.log` (+ `backend.log.1` after rotation) |
| Default app data dir | `{Documents}/Scene Atlas/data` |
| Default image library dir | `{Documents}/Scene Atlas/images` |

**Legacy config migration:** A config containing only `dataDir` (single-root format) is migrated on load to `appDataDir ← dataDir`, `imageLibraryDir ← dataDir/store/images`, `convertToWebp ← false`, and saved immediately.

`userData` is the OS-standard app data path (e.g. `%APPDATA%/Scene Atlas` on Windows, `~/Library/Application Support/Scene Atlas` on macOS).

## Key Files

| File | Purpose |
|------|---------|
| `electron/src/main.ts` | Main process: windows, IPC handlers, sidecar orchestration |
| `electron/src/preload.ts` | Main window preload: exposes `electronAPI` |
| `electron/src/setup.preload.ts` | Setup window preload: exposes `setupAPI` |
| `electron/src/sidecar.ts` | Sidecar spawn, port discovery, stdout parsing |
| `electron/src/config.ts` | Config load/save/migration, default directories |
| `electron/setup.html` | Setup window HTML (first-run directory picker); fonts bundled in `electron/fonts/`, so it needs no network and its CSP has no remote origins |
| `electron/loading.html` | Startup / error page shown until the sidecar serves the UI |
| `electron-builder.yml` | Build targets, sidecar bundling, auto-update config |
| `backend/pyinstaller/scene_atlas_backend.spec` | PyInstaller spec for freezing the Python backend |
| `backend/pyinstaller/entry.py` | Sidecar entry point |
