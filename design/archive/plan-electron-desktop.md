# Plan: Bundle Scene Atlas as an Electron Desktop App

**Status**: Planned (not yet started) — comparison alternative to [plan-tauri-desktop.md](plan-tauri-desktop.md)
**Created**: 2026-02-23

## Context

Same goal as the Tauri plan: package Scene Atlas as a native desktop app for non-technical users. This plan uses Electron instead of Tauri, with the Python backend as a PyInstaller-frozen sidecar. The existing dev workflow (`uv` + `npm`) continues to work unchanged.

**Targets**: Windows x86_64, macOS x86_64 + aarch64, Linux x86_64
**CLIP model**: Download on first launch (~600MB from HuggingFace), not bundled
**Expected installer size**: ~450-650MB (Electron adds ~150MB over the Tauri plan)

---

## Architecture

```
Dev mode (unchanged):
  Terminal 1: uv run uvicorn backend.app.main:app --port 8000
  Terminal 2: cd frontend && npm run dev  (Vite :5173, proxies /api -> :8000)

Electron dev mode:
  npm run electron:dev
    -> Vite dev server starts on :5173
    -> Electron main process spawns Python sidecar on a free port
    -> BrowserWindow loads http://localhost:5173

Electron production:
  User launches Scene Atlas.exe/.app
    -> Electron shows splash BrowserWindow (loading screen)
    -> Main process spawns PyInstaller-frozen backend: --port <free> --data-dir <appdata>
    -> Backend prints "SCENE_ATLAS_READY port=XXXXX" to stdout
    -> Main process reads port, sends via IPC to renderer
    -> Renderer stores port, loads the app
    -> Loading screen dismissed when /health returns 200
```

### Data Directory (identical to Tauri plan)

| Mode | Location |
|------|----------|
| Dev (no Electron) | `<project>/data/` (unchanged) |
| Electron dev | `<project>/data/` |
| Electron production | Platform app data dir via `--data-dir` |

Production paths: `%APPDATA%/Scene Atlas/data` (Win), `~/Library/Application Support/Scene Atlas/data` (mac), `~/.config/scene-atlas/data` (Linux)

---

## Implementation Phases

### Phase 1: Backend Preparation (identical to Tauri plan)

**No differences.** The same `config.py` path recomputation, `main.py` CLI args + ready signal, and `pyinstaller/entry.py` frozen entry point apply. See [plan-tauri-desktop.md](plan-tauri-desktop.md) Phase 1 for details.

Only CORS difference — Electron's renderer runs on `http://localhost` or loads from `file://`, not a custom protocol:
```python
cors_origins: list[str] = [
    "http://localhost:3000", "http://localhost:5173",
    "http://localhost:*",  # Electron renderer
    "file://",             # Electron production (if loading from file)
]
```

In practice, since Electron's BrowserWindow makes requests to `http://localhost:{port}`, CORS is simpler — it's just standard localhost-to-localhost, no custom protocol schemes.

---

### Phase 2: Frontend URL Abstraction (identical to Tauri plan)

**Nearly identical.** The same `apiBase.ts`, axios interceptor, and URL helper changes apply. The only difference is the gate component:

**`frontend/src/components/DesktopGate.tsx`** — Backend readiness gate

```typescript
// In Electron mode, main process sends port via IPC
// In non-Electron mode (dev), renders children immediately
export function DesktopGate({ children }) {
  const isElectron = !!(window as any).electronAPI
  const [ready, setReady] = useState(!isElectron)

  useEffect(() => {
    if (!isElectron) return
    // Preload script exposes electronAPI.onBackendReady()
    ;(window as any).electronAPI.onBackendReady((port: number) => {
      ;(window as any).__SCENE_ATLAS_PORT__ = port
      // Now poll /health until 200
      const interval = setInterval(async () => {
        try {
          const res = await fetch(`http://localhost:${port}/health`)
          if (res.ok) { setReady(true); clearInterval(interval) }
        } catch {}
      }, 1500)
    })
  }, [isElectron])

  if (!ready) return <LoadingScreen />
  return <>{children}</>
}
```

The `LoadingScreen` component is the same as the Tauri plan.

---

### Phase 3: Electron Scaffolding

This is where the plans diverge significantly.

**3a. Project structure:**

```
scene-atlas/                       (project root)
+-- electron/                      <-- NEW: Electron main process
|   +-- main.ts                    <-- Main process entry (window + sidecar)
|   +-- preload.ts                 <-- Preload script (IPC bridge)
|   +-- sidecar.ts                 <-- Sidecar lifecycle management
|   +-- tsconfig.json              <-- Separate TS config for Node target
+-- frontend/                      (unchanged)
+-- backend/                       (unchanged)
+-- package.json                   <-- NEW: root package.json for Electron
+-- electron-builder.yml           <-- NEW: electron-builder config
```

**Key difference from Tauri**: Requires a **root `package.json`** because electron-builder expects to be at the project root. The frontend `package.json` stays separate.

**3b. Root `package.json`:**
```json
{
  "name": "scene-atlas",
  "version": "0.1.0",
  "main": "electron/dist/main.js",
  "scripts": {
    "electron:dev": "concurrently \"cd frontend && npm run dev\" \"tsc -p electron/tsconfig.json && electron .\"",
    "electron:build": "tsc -p electron/tsconfig.json && electron-builder"
  },
  "devDependencies": {
    "electron": "^33.0.0",
    "electron-builder": "^25.0.0",
    "concurrently": "^9.0.0",
    "typescript": "^5.0.0",
    "get-port": "^7.0.0"
  }
}
```

**3c. `electron/main.ts`** — Main process:

```typescript
import { app, BrowserWindow } from 'electron'
import { spawn } from 'child_process'
import getPort from 'get-port'
import path from 'path'

let mainWindow: BrowserWindow
let sidecarProcess: ChildProcess

app.whenReady().then(async () => {
  // 1. Create window with loading screen
  mainWindow = new BrowserWindow({
    width: 1400, height: 900,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    }
  })

  // 2. Pick a free port
  const port = await getPort()

  // 3. Resolve data directory
  const dataDir = app.isPackaged
    ? path.join(app.getPath('userData'), 'data')
    : path.join(__dirname, '..', 'data')

  // 4. Resolve sidecar binary path
  const sidecarPath = app.isPackaged
    ? path.join(process.resourcesPath, 'sidecar', 'scene-atlas-backend')
    : null  // In dev, backend runs separately

  // 5. Spawn sidecar
  if (sidecarPath) {
    sidecarProcess = spawn(sidecarPath, [
      '--port', String(port),
      '--data-dir', dataDir,
    ])

    sidecarProcess.stdout.on('data', (data) => {
      const line = data.toString()
      if (line.includes('SCENE_ATLAS_READY')) {
        mainWindow.webContents.send('backend-ready', port)
      }
    })

    sidecarProcess.stderr.on('data', (data) => {
      console.error('[backend]', data.toString())
    })
  }

  // 6. Load frontend
  if (app.isPackaged) {
    mainWindow.loadFile(path.join(__dirname, '..', 'frontend', 'dist', 'index.html'))
  } else {
    mainWindow.loadURL('http://localhost:5173')
  }
})

// Kill sidecar on quit
app.on('will-quit', () => {
  if (sidecarProcess) {
    sidecarProcess.kill()
  }
})
```

**3d. `electron/preload.ts`** — IPC bridge:

```typescript
import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('electronAPI', {
  onBackendReady: (callback: (port: number) => void) => {
    ipcRenderer.on('backend-ready', (_event, port) => callback(port))
  }
})
```

**3e. `electron-builder.yml`:**

```yaml
appId: com.sceneatlas.app
productName: Scene Atlas
directories:
  output: dist-electron
files:
  - electron/dist/**/*
  - frontend/dist/**/*
extraResources:
  - from: backend/pyinstaller/dist/scene-atlas-backend/
    to: sidecar
    filter:
      - "**/*"
win:
  target: [nsis]
  icon: assets/icon.ico
mac:
  target: [dmg]
  icon: assets/icon.icns
  category: public.app-category.utilities
linux:
  target: [AppImage, deb]
  icon: assets/icon.png
  category: Utility
```

**3f. Update `.gitignore`**: add `electron/dist/`, `dist-electron/`, `node_modules/` (root)

**Verify**: `npm run electron:dev` opens window pointing at Vite dev server.

---

### Phase 4: PyInstaller Packaging (identical to Tauri plan)

**No meaningful differences.** Same `--onedir` approach, same spec file, same gotchas with torch/qdrant/opencv.

The only difference is where the output goes:
- Tauri: `src-tauri/binaries/` with target-triple suffix on the executable
- Electron: `backend/pyinstaller/dist/scene-atlas-backend/` (electron-builder's `extraResources` copies it during build)

**Electron advantage**: No target-triple naming convention. `extraResources` just copies the directory as-is. Simpler.

---

### Phase 5: Full Build + CI/CD

**5a. Build commands:**
```bash
uv run python scripts/build_sidecar.py           # PyInstaller
cd frontend && npm run build                       # Vite build
cd .. && npm run electron:build                    # electron-builder
```

**5b. `.github/workflows/electron-build.yml`** — Matrix of 4 jobs:

| Runner | Target |
|--------|--------|
| `windows-latest` | Windows x64 (NSIS installer) |
| `macos-latest` | macOS ARM64 (DMG) |
| `macos-13` | macOS Intel (DMG) |
| `ubuntu-22.04` | Linux x64 (AppImage + deb) |

Each job: install Node + Python/uv + system deps -> build sidecar -> `electron-builder` -> upload artifact.

**No Rust toolchain needed** (unlike Tauri).

**5c. Auto-updates:**

electron-builder has first-class support for auto-updates via `electron-updater`:
- Publishes update metadata alongside installers
- App checks for updates on launch (or periodically)
- Downloads and applies updates automatically
- Supports GitHub Releases, S3, or generic HTTP server as update source

This is significantly more mature than Tauri's updater plugin.

---

## Comparison: Electron vs Tauri

| Aspect | Electron | Tauri |
|--------|----------|-------|
| **Shell size** | ~150MB (bundled Chromium) | ~5-10MB (system webview) |
| **Runtime memory** | ~100MB baseline | ~30MB baseline |
| **Total installer** | ~450-650MB | ~300-500MB |
| **Sidecar management** | TypeScript (familiar) | Rust (new language) |
| **Build toolchain** | Node.js only | Node.js + Rust |
| **CI complexity** | Lower (no Rust install) | Higher (Rust toolchain) |
| **CORS/CSP** | None needed (standard HTTP) | Custom protocol requires CSP config |
| **Auto-update** | Mature (electron-updater) | Newer (tauri-plugin-updater) |
| **Sidecar bundling** | `extraResources` (copy directory) | `externalBin` (target-triple naming) |
| **IPC** | `ipcMain`/`ipcRenderer` + preload | Tauri events + commands |
| **Security model** | Must configure `contextIsolation` | Secure by default (capabilities) |
| **Native APIs** | Extensive (tray, menu, notifications, etc.) | Good but fewer (growing) |
| **Ecosystem maturity** | Very mature, huge community | Younger, growing fast |
| **macOS universal binary** | Supported by electron-builder | Manual fat binary needed |
| **Root package.json** | Required (new file) | Not required |

### Where Electron Wins
- **No Rust needed** — entire app is JS/TS + Python, no new language to learn
- **Simpler sidecar bundling** — `extraResources` just copies a directory, no naming conventions
- **No CSP headaches** — standard Chromium, no webview protocol quirks
- **Mature auto-updates** — electron-updater is battle-tested
- **macOS universal binary** — electron-builder handles it natively
- **Familiar debugging** — Chrome DevTools in production builds

### Where Tauri Wins
- **~150MB smaller installers** — no bundled Chromium
- **~70MB less runtime memory** — system webview is lighter
- **Stronger security defaults** — capability-based permissions, no Node.js in renderer
- **No root package.json** — cleaner project structure
- **Smaller attack surface** — no Chromium CVEs to track

### Shared Work (Framework-Agnostic)

Phases 1, 2, and 4 are **identical** regardless of choice:
- Backend: config.py path recomputation, main.py CLI args + ready signal, PyInstaller entry point
- Frontend: dynamic base URL, axios interceptor, URL helpers, readiness gate, loading screen
- PyInstaller: same spec file, same torch/qdrant gotchas

This means you can implement these phases first and defer the Electron-vs-Tauri decision to Phase 3.

---

## Files Summary

| File | Action | Phase |
|------|--------|-------|
| `backend/app/config.py` | Modify: path recomputation, CORS | 1 |
| `backend/app/main.py` | Modify: CLI args, ready signal | 1 |
| `backend/pyinstaller/entry.py` | **New**: frozen entry point | 1 |
| `frontend/src/lib/apiBase.ts` | **New**: `getApiBaseUrl()`, `resolveApiUrl()` | 2 |
| `frontend/src/lib/api.ts` | Modify: interceptor, URL helpers | 2 |
| `frontend/src/components/DesktopGate.tsx` | **New**: backend readiness gate | 2 |
| `frontend/src/components/LoadingScreen.tsx` | **New**: splash screen | 2 |
| `frontend/src/main.tsx` | Modify: wrap with DesktopGate | 2 |
| `package.json` (root) | **New**: Electron deps + scripts | 3 |
| `electron/main.ts` | **New**: main process | 3 |
| `electron/preload.ts` | **New**: IPC bridge | 3 |
| `electron/sidecar.ts` | **New**: sidecar lifecycle | 3 |
| `electron-builder.yml` | **New**: build config | 3 |
| `backend/pyinstaller/scene_atlas_backend.spec` | **New**: PyInstaller config | 4 |
| `scripts/build_sidecar.py` | **New**: build automation | 4 |
| `.github/workflows/electron-build.yml` | **New**: CI/CD pipeline | 5 |
| `.gitignore` | Modify: Electron artifacts | 3 |

## Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| PyInstaller + torch fragility | **High** | Same as Tauri — `--collect-all torch`, CPU-only wheels |
| Qdrant native libs not bundled | Medium | Same as Tauri — explicit verification |
| Installer size (~600MB+) | Medium | Acceptable given Python sidecar already dominates |
| Windows AV flagging | Medium | Code-signing certificate (electron-builder has signing built in) |
| Chromium CVE tracking | Low | Keep Electron updated; Dependabot helps |

## Verification

Same as Tauri plan:
1. Dev workflow preserved: `uv run uvicorn ...` + `npm run dev` still works
2. Backend CLI args work standalone
3. All frontend + backend tests pass
4. `npm run electron:dev` opens window, backend starts on dynamic port
5. `npm run electron:build` produces installer
6. First-run CLIP download shows loading screen
7. Closing window kills sidecar (no orphans)
