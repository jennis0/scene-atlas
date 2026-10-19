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
     ├── YES → launchApp(appDataDir, imageLibraryDir)
     │         → createMainWindow()
     │         → isDev?
     │         │   ├── YES → load the Vite dev server (developer runs the backend on port 8000)
     │         │   └── NO  → load loading.html
     │         │              → prepareStorageDirs()  (create + write-test both roots; error page if unusable)
     │         │              → findFreePort(47816)
     │         │              → spawnSidecar(port, appDataDir, imageLibraryDir)
     │         │              → sidecar prints SCENE_ATLAS_READY (once uvicorn is listening)
     │         │              → poll /health → loadURL(http://127.0.0.1:<port>/)
     │         └── App.tsx checks /models/setup-status → SetupWizard or gallery
     └── NO  → showSetupWindow()
              → user picks appDataDir and imageLibraryDir
              → setup:complete IPC → validate + prepareStorageDirs → saveConfig → launchApp(...)
```

The main process remembers the last `backend-error` and re-sends it on every `did-finish-load`, and the preload caches it, so the loading page receives it even after a reload.

### Storage folder checks

`electron/src/storageDirs.ts` (no `electron` import, unit tested with `node --test` in `electron/test/`) holds the checks on the two roots:

- **`prepareStorageDirs`** creates both roots and write-tests them, on setup, on a storage change and on every launch (a drive may have been unmounted).
- **`hasForeignEntries`** is used by `pickStorageDir()` in `main.ts` whenever the user picks either folder, in setup or in Settings. When the folder already holds entries Scene Atlas didn't create, a native warning offers *Choose Another Folder* (the default) or *Use This Folder*. The likely case is someone pointing the image library at their existing map collection: Scene Atlas would never show those files, and the reset instructions say to delete the library folder. Its own entries are dotfiles, two-character lower-case hex shards, `backups` and the app data entries (`battlemap.db*`, `lancedb`, `store`, `logs`, …), plus OS clutter. Both lists are accepted in either folder, so one folder for both is allowed (the backend's storage lock is per resolved root, so that's safe), and so is a folder that contains the other root. Update the lists whenever the backend writes a new top-level entry to either root.

The Electron setup window only chooses storage directories. Everything else (appearance, stored format, tag packs, search model) is the React setup wizard, the same in every mode (see [first-run.md](first-run.md)). The UI's display choices and colours are kept in the config too, so every window, the title bar included, follows the theme chosen in the app (see [first-run.md](first-run.md#desktop-display-choices-and-window-colours)).

## IPC Channels

Every handler is registered through `handleTrusted()`, which rejects calls whose sender frame is not an app URL (`isAppUrl()` in `main.ts`). Windows are hardened: `window.open` is denied and navigation away from the app is blocked; http(s) links open in the system browser.

### Setup Window (via `setupAPI`, `electron/src/setup.preload.ts`)

| Channel | Direction | Purpose |
|---------|-----------|---------|
| `setup:get-default-dirs` | renderer → main | Returns `{ appDataDir, imageLibraryDir }` defaults (`<base>/data` and `<base>/images`; see [Config Storage](#config-storage)) |
| `setup:choose-directory` | renderer → main | `(kind, currentDir, otherRoot)`: opens the folder picker at `currentDir` with the non-empty-folder warning (`pickStorageDir`), returns the chosen path or null |
| `setup:complete` | renderer → main | `(appDataDir, imageLibraryDir)`: validates absolute paths, creates and write-tests both roots, saves config, launches app, closes setup. Returns `{ error: string \| null }` |

### Main Window (via `electronAPI`, `electron/src/preload.ts`)

| Channel | Direction | Purpose |
|---------|-----------|---------|
| `backend-error` | main → loading page | Error message if the sidecar fails to start or crashes |
| `system:get-app-data-dir` | renderer → main | Returns current app data directory path |
| `system:get-image-library-dir` | renderer → main | Returns current image library directory path |
| `system:choose-app-data-dir` | renderer → main | Folder picker (with the non-empty-folder warning) for a new app data location |
| `system:choose-image-library-dir` | renderer → main | Folder picker (with the non-empty-folder warning) for a new image library location |
| `system:change-storage-dirs` | renderer → main | Validates and prepares the new roots, saves config, stops the sidecar, relaunches the app. Resolves with `{ error }` only if the new locations are rejected |
| `prefs:get-sync` | preload → main | Synchronous (`sendSync`), once per page load: the config's `displayPrefs`, exposed as `electronAPI.displayPrefs` |
| `prefs:set` | renderer → main | `(key, value)`: saves one display choice (validated); the theme also sets `nativeTheme.themeSource` |
| `window:set-colors` | renderer → main | `{ background, foreground }` hex: sets the window background and the Windows title-bar overlay, and saves them for the next launch |

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

Imports name local files by path ([local-ingest.md](local-ingest.md)): the preload exposes `getPathForFile` (`webUtils.getPathForFile`, for dropped items) and `chooseImportFolders` / `chooseImportFiles` (native pickers via `imports:choose-folders` / `imports:choose-files`, registered with `handleTrusted`). They only return paths the user picked; the backend reads the files.

## Sidecar Lifecycle

1. **Port discovery** — `findFreePort(47816)` uses the preferred port if free, otherwise binds `127.0.0.1:0` for an OS-assigned port
2. **Spawn** — `spawn(sidecarPath, ['--port', port, '--app-data-dir', appDataDir, '--image-library-dir', imageLibraryDir, '--parent-pid', process.pid])`, stdin/stdout/stderr piped (stdin is never written to; see the parent watchdog below). Sidecar path: `path.join(process.resourcesPath, 'sidecar', 'scene-atlas-backend[.exe]')`. Configuration goes on the command line, not in environment variables.
3. **Ready signal** — `entry.py` runs uvicorn through a `uvicorn.Server` subclass that prints `SCENE_ATLAS_READY port=…` after startup has bound the socket (so after the lifespan, too). The main process scans stdout for it, polls `/health`, then loads the UI from the sidecar. Only the sidecar prints the marker; other launchers (E2E, the stress runner) poll `/health`
4. **Logging** — stdout/stderr appended to `{userData}/backend.log`; the log is rotated to `backend.log.1` when it exceeds 5 MB at startup
5. **Failure handling** — Spawn errors, any exit before ready, and a non-zero exit after ready send `backend-error` with the last 10 output lines and the log path. `loading.html` headlines the last Python exception message in those lines (e.g. another backend already holding the data folder's lock, see [backend.md](backend.md#startup-sequence-mainpy-lifespan)), else the first line of the error
6. **Shutdown** — `stopSidecar()` closes the sidecar's stdin and, except on Windows, sends `SIGTERM`, then waits (5 s by default); on Windows, where `kill()` is `TerminateProcess`, it kills the sidecar only if it is still running after that. `will-quit` holds the quit (`preventDefault`) until it resolves, for up to `QUIT_GRACE_MS` (15 s). That wait is what makes the stop graceful on Windows: libuv puts every spawned child in a job object with `KILL_ON_JOB_CLOSE`, so the sidecar is terminated the moment Electron exits; before the wait, every normal close killed the backend mid-shutdown (found by the packaged-app tests). Also called on macOS's `window-all-closed` (the app stays in the dock) and before relaunching for a storage change. The backend logs `Shutdown complete` when its lifespan has finished
7. **Parent watchdog** — (macOS and Linux; on Windows the job object ends the sidecar with Electron, abruptly, before the watchdog can act) `--parent-pid` turns on `backend/app/parent_watchdog.py` in the sidecar, so it never outlives Electron (crash, force-quit, `app.exit()` without `will-quit`). It fires when stdin reaches EOF (the OS closes Electron's end of the pipe however Electron exits, on every platform) or when a 2 s poll finds the parent PID gone (psutil, so a reused PID doesn't count; covers an unreadable stdin). Firing sets the uvicorn server's `should_exit`, which runs the normal graceful shutdown (ingest batch, storage locks); if the process is still alive 90 s later it calls `os._exit(1)`. Without the flag (dev, server mode) stdin is ignored

In dev mode the sidecar is not spawned — the developer runs the backend on port 8000.

## Window Frame

`frameOptions()` in `windowFrame.ts`; the frontend's counterpart is `windowChrome` in `frontend/src/lib/appMode.ts`.

| Platform | Frame | Title bar drawn by |
|---|---|---|
| macOS | `titleBarStyle: 'hiddenInset'` | The page (gallery header, `WindowDragBar`), around the native traffic lights |
| Windows | `titleBarStyle: 'hidden'` with `titleBarOverlay` (32px, the UI's background and text colours) | The page, beside Electron's caption buttons |
| Linux | The window manager's own frame | The system |

Linux kept the borderless overlay until 2026-10-19 ([ADR-022](decisions.md#adr-022-system-title-bar-on-linux-and-desktop-zoom)). Electron draws GNOME-style (Adwaita) caption buttons there, circles that look wrong on any other desktop, and a system frame matches the desktop's theme and scaling. On macOS and Windows, pages mark drag regions (`isFrameless`); on Linux they don't need to, and the gallery header drops the overlay's top band.

The caption buttons and traffic lights keep their size whatever the zoom or Text size, so the room the page leaves for them is in window pixels: `TITLE_BAR_BAND` (32 px, the overlay's height) and `TRAFFIC_LIGHT_INSET` (80 px) in `appMode.ts` divide by `--zoom`, which `lib/zoom.ts` sets on the root element. In rem the band grew with Text size, and in plain px it would grow with zoom, leaving an empty strip at 200% and header controls under the buttons at 80%. Chromium's `env(titlebar-area-*)` values would do the same job, but whether they account for page zoom is unverified.

### Window state

The main window opens at the size and position it was last left at, maximised if it was (`windowState.ts`, saved as `windowState` in the config on resize, move, maximise and close; the un-maximised bounds come from `getNormalBounds`). `restoredBounds` keeps the size between the minimum (900×600) and the screen it opens on, so the 1400×900 default also fits a 1366×768 laptop, and keeps the position only while 100×20 px of the window's top edge is on a screen, so a window last on an unplugged monitor opens on the primary one. Wayland compositors place windows themselves and ignore the position. The setup window isn't remembered.

### Zoom

Settings → Appearance → Zoom (80–200%, desktop only: a browser has its own) and Ctrl + / − / 0 (⌘ on macOS). It scales the whole page, images included; Text size scales only text and its spacing. Kept as the `scene-atlas-zoom` display choice ([first-run.md](first-run.md#desktop-display-choices-and-window-colours)), not Chromium's per-origin zoom, which is lost whenever the backend's port changes.

- The preload applies the saved zoom with `webFrame.setZoomFactor` before the page paints (the loading page too), and exposes `setZoom(percent)`.
- `frontend/src/lib/zoom.ts` keeps the level and handles the shortcuts (`zoomStepForKey`, a `keydown` listener that prevents the default), for the Settings control and the keys alike.
- The page, not the main process, handles the keys: Playwright's key presses (CDP) skip `before-input-event`, so a main-process handler couldn't be tested, and the menus have no zoom items to clash with ([Menus](#menus)).

### Menus

`removeMenu()` and `setMacMenu()` in `windowFrame.ts`. Electron's default menu had zoom shortcuts that changed the zoom without saving it, plus Reload and Toggle Developer Tools, which a release shouldn't offer. Windows and Linux windows have no menu (Chromium handles copy, paste and undo itself; on Linux the frame would show the menu as a bar). macOS keeps the app, Edit and Window menus, and View with full screen only. In dev, F12 still opens DevTools.

**HiDPI.** Electron follows the desktop's scale on Linux (Wayland, or `Xft.dpi`/`GDK_SCALE` on X11). WSLg reports none: a 4K screen arrives as 3840×2160 at scale 1, so Linux apps there are tiny. That's the WSL setup, not the app: set `GDK_SCALE=2` in WSL ([building.md](../docs/development/building.md)), or use Zoom.

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

**Sidecar build environment:** `build_sidecar.py` runs PyInstaller from `.venv-sidecar`, which `uv sync --frozen --managed-python --no-install-project --extra <ort_extra> --group sidecar` keeps at exactly the runtime dependencies plus PyInstaller (the `sidecar` dependency group). PyInstaller bundles every module it can import, optional imports included, so building from the dev venv used to bundle IPython, prompt_toolkit, pygments, transformers' safetensors and onnx's protobuf. A package that isn't installed can't be bundled, so the spec needs no dev-tool excludes. The Python is uv-managed (as in CI), never a system or Microsoft Store one.

**Package metadata and the self-check:** the spec bundles every distribution's `.dist-info` (`copy_metadata` over the build venv, minus PyInstaller's own), since packages read their metadata at import: `httpcore2` and `httpx2` call `importlib.metadata.version()` on themselves, so before this the frozen app couldn't download a model ("No package metadata was found for httpcore2"). PyInstaller only bundles metadata when a hook asks, and a whitelist of packages known to read it broke as soon as a dependency started to. The spec also writes `self_check_modules.json` (the runtime deps' top-level modules, listed at build time while all the metadata exists); `scene-atlas-backend --self-check` imports each one that was bundled, and `smoke_sidecar.py` runs it before starting the server. That catches frozen-only import failures on paths startup never touches (model downloads, video).

**What the spec leaves out:** each was checked against the PE import tables of the bundled binaries and the importing code's `try/except ImportError`:

- pyarrow's Arrow Flight, Substrait and cloud filesystems (`_flight`, `_substrait`, `_s3fs`, `_gcsfs`, `_azurefs`, `_hdfs`; on Windows also the `arrow_flight`/`arrow_python_flight`/`arrow_substrait`/`arrow_s3` DLLs only they load. On macOS and Linux those libraries stay: pyarrow's core lib links `libarrow_substrait` directly), plus the headers, Cython sources, import libraries and tests the wheel ships. LanceDB uses none of them.
- Pillow's AVIF codec (`PIL._avif`, 7 MB); AVIF isn't an import format.
- Not `hf_xet`, which an earlier spec excluded: the model repos are on Hugging Face's Xet storage, and huggingface-hub 2.x can't download Xet files without it.

**Size** (Windows, 2026-10-18; the installer is the download):

| | Before | After |
|---|---|---|
| Installer (`Scene-Atlas-Setup-<version>.exe`) | 306 MB | 275 MB |
| Installed | 1,044 MB | 929 MB |
| of which the sidecar | 675 MB | 607 MB |
| of which Electron | 369 MB | 321 MB |

The rest is hard to cut: `_lancedb.pyd` alone is 225 MB (kept, see [status-and-roadmap.md](status-and-roadmap.md)), OpenCV 111 MB (grid detection; its 29 MB ffmpeg library decodes video thumbnails), onnxruntime + DirectML 63 MB, scipy 67 MB (grid detection imports `scipy.signal`, which pulls in optimize, sparse and the rest). Electron's own runtime files (`dxcompiler.dll`, `vk_swiftshader.dll`, ...) are left alone: Chromium loads them on demand, and which it needs changes between releases.

**Locales:** `electronLanguages` keeps `en-US` and `en-GB` (46 MB of other locale packs dropped). Chromium sets the renderer's locale (`navigator.language`, the `Intl` default) from the packs present, falling back to `en-US`; `en-GB` keeps UK date and number formats on UK systems. The UI is English only, so other systems get `en-US` formats.

### Fuses

`electronFuses` in `electron-builder.yml` flips these in the packaged binary:

| Fuse | Value | Why |
|---|---|---|
| `runAsNode` | off | `ELECTRON_RUN_AS_NODE` would turn the app into a plain Node runtime |
| `enableNodeOptionsEnvironmentVariable` | off | `NODE_OPTIONS` could preload code into the main process |
| `enableNodeCliInspectArguments` | off | `--inspect` would open a debugger on the main process |
| `enableEmbeddedAsarIntegrityValidation` + `onlyLoadAppFromAsar` | on | only the shipped, hash-checked `app.asar` is loaded |
| `grantFileProtocolExtraPrivileges` | **on** (default) | Off, `file://` can't read inside `app.asar`, so `setup.html` and `loading.html` fail with `ERR_FILE_NOT_FOUND` (found by the packaged-app tests). Turning it off needs those pages served from a custom protocol (`protocol.handle`), with `isAppUrl()` and the IPC sender checks moved to that scheme |

With `--inspect` gone, Playwright's `_electron.launch` can't drive the packaged app; the packaged-app tests use `--remote-debugging-port` and CDP instead ([testing.md](testing.md#packaged-app-tests)).

**Models:** ONNX models are not bundled. They are downloaded from Hugging Face at runtime by `model_download_service`; first launch therefore needs an internet connection (see [hf-model-management.md](hf-model-management.md)).

### GPU support in desktop builds

There is one build per platform; GPU support comes from the onnxruntime package installed in the sidecar build venv, selected by `build_sidecar.py --ort-extra` (default: `gpu-directml` on Windows, `cpu` elsewhere; the release matrix passes its `ort_extra`):

| Platform | `ort_extra` | ORT package | GPU provider |
|----------|-------------|-------------|--------------|
| Windows | `gpu-directml` | `onnxruntime-directml` | DirectML (any DirectX 12 GPU) |
| macOS | `cpu` | `onnxruntime` | CoreML (built into the macOS wheel) |
| Linux | `cpu` | `onnxruntime` | none (CPU only) |

The PyInstaller spec keeps onnxruntime's `entry_points.txt` (DirectML plugin registration). UPX is off: it corrupted bundled shared libraries (numpy's OpenBLAS), slows startup and trips Windows antivirus. At runtime `ort_providers.py` resolves the provider and falls back to CPU (see [gpu-acceleration.md](gpu-acceleration.md)).

**Releases and updates:** there is no auto-updater, so electron-builder publishes nothing (`publish: null`) and writes no update metadata (`latest.yml`, `.blockmap`). The Release workflow's `publish` job creates the GitHub Release `v<version>` from the three builds' installers, and only once all three have passed. An updater would need code signing first: an unsigned Windows installer warns in SmartScreen on every update. macOS builds are signed and notarized only when the Apple signing secrets are set (none are yet); the build step unsets empty ones, because electron-builder reads an empty `CSC_LINK` as a path and fails.

**Windows specifics:** installers are named without spaces (`Scene-Atlas-Setup-<version>.exe`; GitHub rewrites spaces in asset names). electron-builder picks up `assets/icon.ico`, `icon.icns` and `icon.png` by name from `buildResources` ([brand.md](brand.md) covers how they're drawn). `main.ts` sets the AppUserModelID to the `appId`, matching the installer's shortcuts, or a pinned shortcut and the running app show as two taskbar icons. The sidecar is spawned with `windowsHide`: it is a console program, and Windows would otherwise open a console window beside the app.

## Config Storage

| Item | Location |
|------|----------|
| App config | `{userData}/scene-atlas-config.json` — `{ appDataDir, imageLibraryDir, displayPrefs?, windowColors?, windowState? }` (`windowState`: see [Window state](#window-state)). `displayPrefs` and `windowColors` are the UI's display choices and colours (see [first-run.md](first-run.md#desktop-display-choices-and-window-colours)); they're sanitised on load (`displayPrefs.ts`). Older configs may also hold `convertToWebp` or `pendingStoredFormat`, which are ignored: the stored format is chosen in the setup wizard |
| Backend log | `{userData}/backend.log` (+ `backend.log.1` after rotation) |
| Default app data dir | Windows: `%LOCALAPPDATA%/Scene Atlas/data`; macOS, Linux: `{Documents}/Scene Atlas/data` |
| Default image library dir | Windows: `%LOCALAPPDATA%/Scene Atlas/images`; macOS, Linux: `{Documents}/Scene Atlas/images` |

On Windows, Documents is often redirected into OneDrive (the Windows 11 default for many accounts), which would sync the SQLite database, the LanceDB index and the thumbnails while they're open (lock conflicts, Files On-Demand evicting them) as well as every library image. Local AppData is never synced or roamed. `defaultStorageBase()` in `storageDirs.ts` chooses (unit tested); existing configs keep their folders.

**Legacy config migration:** A config containing only `dataDir` (single-root format) is migrated on load to `appDataDir ← dataDir`, `imageLibraryDir ← dataDir/store/images`, and saved immediately. A `convertToWebp` field from older configs is ignored: the sidecar of that version already seeded the setting from it.

`userData` is the OS-standard app data path (e.g. `%APPDATA%/Scene Atlas` on Windows, `~/Library/Application Support/Scene Atlas` on macOS).

## Key Files

| File | Purpose |
|------|---------|
| `electron/src/main.ts` | Main process: windows, IPC handlers, sidecar orchestration |
| `electron/src/preload.ts` | Main window preload: exposes `electronAPI` |
| `electron/src/setup.preload.ts` | Setup window preload: exposes `setupAPI` |
| `electron/src/sidecar.ts` | Sidecar spawn, port discovery, stdout parsing |
| `electron/src/config.ts` | Config load/save/migration, default directories |
| `electron/src/windowFrame.ts` | Frame per platform, menus, starting colours, and where the main window opens and how its state is saved |
| `electron/src/windowState.ts` | The main window's saved bounds: validation and where it reopens (tests in `electron/test/`) |
| `electron/src/displayPrefs.ts` | Validation for display choices and window colours from the UI or config; `themeSourceFor` (tests in `electron/test/`) |
| `electron/src/storageDirs.ts` | Storage folder checks: create + write-test, non-empty-folder detection (tests in `electron/test/`, run with `npm run test:electron`) |
| `electron/setup.html` | Setup window HTML (first-run directory picker); fonts bundled in `electron/fonts/`, so it needs no network and its CSP has no remote origins |
| `electron/loading.html` | Startup / error page shown until the sidecar serves the UI |
| `electron-builder.yml` | Build targets, sidecar bundling, locales, fuses |
| `scripts/build/build_sidecar.py` | Syncs `.venv-sidecar` and runs PyInstaller |
| `scripts/build/build_electron.py` | Frontend → sidecar → TypeScript → electron-builder (`--dev` for an unpacked app only) |
| `scripts/build/smoke_sidecar.py` | Runs the built sidecar's `--self-check`, then starts it and checks it serves the API and UI |
| `e2e/packaged/` | Packaged-app tests (windows, sidecar lifecycle), `npm run test:packaged` |
| `backend/pyinstaller/scene_atlas_backend.spec` | PyInstaller spec for freezing the Python backend |
| `backend/pyinstaller/entry.py` | Sidecar entry point |
