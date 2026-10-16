# Electron Desktop App

Scene Atlas ships as a desktop app using Electron. The Electron shell handles windowing and native OS integration while the Python backend runs as a sidecar subprocess.

## Architecture

```
┌──────────────────────────────────────────────────┐
│  Electron Main Process  (electron/src/main.ts)   │
│  ┌────────────────┐  ┌────────────────────────┐  │
│  │  Setup Window   │  │  Main Window            │  │
│  │  (first-run)    │  │  React app from         │  │
│  │  setup.html     │  │  frontend/dist/         │  │
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

- **Main process** — Window lifecycle, IPC handlers, sidecar management
- **Preload scripts** — Secure IPC bridges (context-isolated, sandboxed)
- **Renderer** — The React frontend loaded from `frontend/dist/` (packaged) or `localhost:5173` (dev)
- **Sidecar** — PyInstaller-frozen Python backend (FastAPI + Uvicorn), spawned as a child process

## Startup Sequence

```
app.whenReady()
  → loadConfig()
  → config exists?
     ├── YES → launchApp(appDataDir, imageLibraryDir, convertToWebp)
     │         → createMainWindow()
     │         → isDev?
     │         │   ├── YES → send 'backend-ready' with port 8000 (dev server)
     │         │   └── NO  → findFreePort()
     │         │              → spawnSidecar(port, appDataDir, imageLibraryDir, convertToWebp)
     │         │              → sidecar prints SCENE_ATLAS_READY
     │         │              → send 'backend-ready' to renderer
     │         └── renderer shows DesktopGate → polls /health → Gallery
     └── NO  → showSetupWindow()
              → user picks appDataDir, imageLibraryDir, convertToWebp
              → setup:complete IPC → saveConfig → launchApp(appDataDir, imageLibraryDir, convertToWebp)
```

## IPC Channels

### Setup Window (via `setupAPI`)

| Channel | Direction | Purpose |
|---------|-----------|---------|
| `setup:get-default-dirs` | renderer → main | Returns `{ appDataDir, imageLibraryDir }` defaults (`Documents/Scene Atlas/data` and `Documents/Scene Atlas/images`) |
| `setup:choose-directory` | renderer → main | Opens native folder picker, returns single selected path |
| `setup:complete` | renderer → main | Saves config (appDataDir, imageLibraryDir, convertToWebp), closes setup, launches app |

### Main Window (via `electronAPI`)

| Channel | Direction | Purpose |
|---------|-----------|---------|
| `backend-ready` | main → renderer | Delivers backend port number once sidecar is ready |
| `backend-error` | main → renderer | Delivers error message if sidecar crashes |
| `system:get-app-data-dir` | renderer → main | Returns current app data directory path |
| `system:get-image-library-dir` | renderer → main | Returns current image library directory path |
| `system:choose-app-data-dir` | renderer → main | Opens native folder picker for new app data location |
| `system:choose-image-library-dir` | renderer → main | Opens native folder picker for new image library location |
| `system:change-storage-dirs` | renderer → main | Saves new paths (newAppDataDir, newImageLibraryDir), relaunches app |

### Preload API Surface

The renderer accesses IPC via `window.electronAPI`:

```typescript
window.electronAPI = {
  platform: string,                          // 'darwin' | 'win32' | 'linux'
  onBackendReady: (cb) => void,              // one-shot listener
  onBackendError: (cb) => void,              // one-shot listener
  getAppDataDir: () => Promise<string | null>,
  getImageLibraryDir: () => Promise<string | null>,
  chooseAppDataDir: () => Promise<string | null>,
  chooseImageLibraryDir: () => Promise<string | null>,
  changeStorageDirs: (appDataDir, imageLibraryDir) => Promise<void>,
}
```

## Sidecar Lifecycle

1. **Port discovery** — `findFreePort()` binds TCP port 0, reads OS-assigned port, closes socket
2. **Spawn** — `spawn(sidecarPath, ['--port', port, '--app-data-dir', appDataDir, '--image-library-dir', imageLibraryDir], { env: { CONVERT_TO_WEBP: '1' | '0' } })` with piped stdio. `CONVERT_TO_WEBP=1` only seeds the `stored_format` app setting to `webp` on first boot (otherwise `original`); after that, Settings → Stored format is authoritative.
3. **Ready signal** — Main process scans stdout for `SCENE_ATLAS_READY`; when found, sends `backend-ready` IPC to renderer
4. **Logging** — All stdout/stderr written to `{userData}/backend.log` with timestamps
5. **Crash handling** — On non-zero exit, sends `backend-error` IPC with last 10 lines of output
6. **Shutdown** — `SIGTERM` sent on window close and app quit

In dev mode, the sidecar is not spawned — the developer runs the backend manually on port 8000.

## Borderless Window

Uses platform-specific titlebar:
- **macOS:** `titleBarStyle: 'hiddenInset'` (native traffic lights)
- **Windows/Linux:** `titleBarStyle: 'hidden'` with `titleBarOverlay` (system buttons drawn by Electron, themed to match dark UI: `#0e1118` background, `#ede8dc` symbols)

The frontend reserves top padding for the window controls drag region.

## Build & Packaging

**Tool:** electron-builder (`electron-builder.yml`)

**Targets:**
| Platform | Format | Architectures |
|----------|--------|---------------|
| Windows | NSIS installer | x64 |
| macOS | DMG | x64 + arm64 |
| Linux | AppImage + DEB | x64 |

**Sidecar bundling:** The PyInstaller `--onedir` output (`backend/pyinstaller/dist/scene-atlas-backend/`) is copied into `resources/sidecar/` via `extraResources`. At runtime: `path.join(process.resourcesPath, 'sidecar', 'scene-atlas-backend[.exe]')`.

**Models:** ONNX models are NOT bundled in the sidecar. They are downloaded from HuggingFace at runtime by `model_download_service`. On first boot, the `ModelSetupScreen` prompts the user to select and download a model. This requires an internet connection on first launch.

**GPU strategy:** One build per platform — no separate GPU variants. GPU support is baked in by installing the right onnxruntime package at build time:
| Platform | ORT Package | GPU Provider |
|----------|------------|--------------|
| Windows | `onnxruntime-directml` | DirectML (all DirectX 12 GPUs) |
| macOS | `onnxruntime` | CoreML (Apple Silicon, built-in) |
| Linux | `onnxruntime` | CPU only |

The runtime code (`ort_providers.py`) auto-detects available providers and falls back to CPU gracefully.

**Auto-updates:** Configured to publish to GitHub Releases (`publish.provider: github`). Single `latest` channel for all platforms.

## Config Storage

| Item | Location |
|------|----------|
| App config | `{userData}/scene-atlas-config.json` — stores `{ appDataDir: string, imageLibraryDir: string, convertToWebp: boolean }` |
| Backend log | `{userData}/backend.log` — sidecar stdout/stderr |
| Default app data dir | `{Documents}/Scene Atlas/data` |
| Default image library dir | `{Documents}/Scene Atlas/images` |

**Migration:** If an existing config contains only `dataDir` (legacy single-root format), it is automatically migrated: `appDataDir ← dataDir`, `imageLibraryDir ← dataDir/store/images`, `convertToWebp ← false`. The migrated config is persisted immediately.

`userData` is the OS-standard app data path (e.g. `%APPDATA%/Scene Atlas` on Windows, `~/Library/Application Support/Scene Atlas` on macOS).

## Key Files

| File | Purpose |
|------|---------|
| `electron/src/main.ts` | Main process: windows, IPC handlers, sidecar orchestration |
| `electron/src/preload.ts` | Main window preload: exposes `electronAPI` to renderer |
| `electron/src/setup.preload.ts` | Setup window preload: exposes `setupAPI` |
| `electron/src/sidecar.ts` | Sidecar spawn, port discovery, stdout parsing |
| `electron/src/config.ts` | Config load/save, default data directory |
| `electron/setup.html` | Setup window HTML (first-run directory picker) |
| `electron-builder.yml` | Build targets, sidecar bundling, auto-update config |
| `backend/pyinstaller/scene-atlas-backend.spec` | PyInstaller spec for freezing the Python backend |
