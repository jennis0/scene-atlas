import { app, BrowserWindow, ipcMain, IpcMainInvokeEvent, nativeTheme, shell } from 'electron'
import * as fs from 'fs'
import * as path from 'path'
import { ChildProcess } from 'child_process'
import { findFreePort, spawnSidecar } from './sidecar'
import {
  getDefaultDirs,
  loadConfig,
  saveConfig,
  setAsideUnusableConfig,
  updateConfig,
} from './config'
import {
  firstLaunchConfig,
  libraryDirsOf,
  withChosenLibrary,
  withDefaultLibrary,
  type AppConfig,
} from './appConfig'
import {
  isDisplayPref,
  sanitizeWindowColors,
  themeSourceFor,
  THEME_PREF_KEY,
  withDisplayPref,
} from './displayPrefs'
import {
  dirsChanged,
  isFolderKind,
  isMissingOrEmpty,
  parseLibraryDirs,
  provisionalDirsToDelete,
  removeProvisionalDirs,
  unavailableLinkedError,
  type LibraryDirs,
} from './libraryDirs'
import { isAbsolutePath, prepareStorageDirs } from './storageDirs'
import { pickImportPaths, pickLibraryFolder } from './pickers'
import { Updater } from './updater'
import { parseUpdateChoice, type UpdateState } from './updatePolicy'
import {
  frameOptions,
  mainWindowPlacement,
  rememberWindowState,
  removeMenu,
  setMacMenu,
  setTitleBarColors,
} from './windowFrame'

const isDev = !app.isPackaged
const isMac = process.platform === 'darwin'
const isWindows = process.platform === 'win32'
const DEV_SERVER_URL = 'http://localhost:5173'
// A stable port keeps the UI's origin, and so its localStorage, the same across launches.
const PREFERRED_PORT = 47816
const MAX_LOG_BYTES = 5 * 1024 * 1024
// How long quitting waits for the backend's graceful shutdown. An idle backend takes
// about a second; an import batch is cut short after this and recovered next start.
const QUIT_GRACE_MS = 15_000
// The backend's exit code when its library check refused the folders (pyinstaller/entry.py)
const LIBRARY_REFUSED = 4

let mainWindow: BrowserWindow | null = null
let sidecarProcess: ChildProcess | null = null
// The folders the backend runs on (in dev, the config's: the developer runs the backend).
let currentDirs: LibraryDirs | null = null
// The running restartBackend(): nothing else may start a backend until it settles.
let restarting: Promise<void> | null = null
let updater: Updater | null = null

// The packaged UI is served by the sidecar, so its origin is the backend's.
let backendOrigin: string | null = null
// Kept so the loading page can be re-sent the error after a reload.
let backendError: string | null = null
// The failure is about the folders (refused by the library check, or unusable), so the
// loading page also offers to choose them again (design/library-setup.md §3.3).
let backendErrorIsFolders = false

// The installer's shortcuts carry electron-builder's appId as their AppUserModelID; the
// process must match, or Windows shows a pinned shortcut and the running app as two
// taskbar icons.
if (isWindows) app.setAppUserModelId('com.sceneatlas.app')

// Two instances would run two backends against one SQLite/LanceDB store.
const hasInstanceLock = app.requestSingleInstanceLock()
if (!hasInstanceLock) {
  app.quit()
}

const LOADING_PAGE = path.join(__dirname, '..', 'loading.html')

/** True for pages that belong to the app: local pages, plus the dev server or the sidecar. */
function isAppUrl(url: string): boolean {
  try {
    const parsed = new URL(url)
    if (parsed.protocol === 'file:') return true
    if (isDev) return parsed.origin === new URL(DEV_SERVER_URL).origin
    return parsed.origin === backendOrigin
  } catch {
    return false
  }
}

function openExternalSafe(url: string): void {
  try {
    const { protocol } = new URL(url)
    if (protocol === 'http:' || protocol === 'https:') void shell.openExternal(url)
  } catch {
    // Unparseable URL: ignore.
  }
}

/** Keep the window on the app origin; hand web links to the system browser. */
function hardenWindow(win: BrowserWindow): void {
  win.webContents.setWindowOpenHandler(({ url }) => {
    openExternalSafe(url)
    return { action: 'deny' }
  })
  win.webContents.on('will-navigate', (event, url) => {
    if (isAppUrl(url)) return
    event.preventDefault()
    openExternalSafe(url)
  })
  if (isDev) {
    win.webContents.on('before-input-event', (_event, input) => {
      if (input.key === 'F12' || (input.control && input.shift && input.key === 'I')) {
        win.webContents.toggleDevTools()
      }
    })
  }
}

// IPC

function assertTrusted(event: { senderFrame?: Electron.WebFrameMain | null }): void {
  const url = event.senderFrame?.url
  if (!url || !isAppUrl(url)) {
    throw new Error(`Rejected IPC from untrusted origin: ${url ?? '<unknown>'}`)
  }
}

function handleTrusted(
  channel: string,
  listener: (event: IpcMainInvokeEvent, ...args: unknown[]) => unknown,
): void {
  ipcMain.handle(channel, (event, ...args) => {
    assertTrusted(event)
    return listener(event, ...args)
  })
}

// What the UI needs before its first paint, so synchronous on purpose (once per page load):
// - display choices (design/first-run.md): the UI keeps them in the config as well as its
//   localStorage, which is tied to the backend's port;
// - libraryChosen (design/library-setup.md §2.2): the wizard resumes after its library step.
ipcMain.on('prefs:get-sync', (event) => {
  try {
    assertTrusted(event)
    const config = loadConfig()
    event.returnValue = {
      displayPrefs: config?.displayPrefs ?? {},
      libraryChosen: config?.libraryChosen ?? false,
    }
  } catch {
    event.returnValue = { displayPrefs: {}, libraryChosen: false }
  }
})

handleTrusted('prefs:set', (_event, key, value) => {
  const config = loadConfig()
  if (!config || typeof value !== 'string' || !isDisplayPref(key, value)) return
  const prefs = config.displayPrefs ?? {}
  if (prefs[key] === value) return
  updateConfig({ displayPrefs: withDisplayPref(prefs, key, value) })
  if (key === THEME_PREF_KEY) nativeTheme.themeSource = themeSourceFor({ [key]: value })
})

// The UI reports its colours whenever its theme changes, so the window background and the
// Windows/Linux title-bar controls match it, now and at the next launch.
handleTrusted('window:set-colors', (event, raw) => {
  const colors = sanitizeWindowColors(raw)
  const win = BrowserWindow.fromWebContents(event.sender)
  if (!colors || !win) return
  setTitleBarColors(win, colors.background, colors.foreground)
  const saved = loadConfig()?.windowColors
  if (saved?.background !== colors.background || saved?.foreground !== colors.foreground) {
    updateConfig({ windowColors: colors })
  }
})

handleTrusted('imports:choose-folders', (event) => pickImportPaths(event.sender, 'folders'))
handleTrusted('imports:choose-files', (event) => pickImportPaths(event.sender, 'files'))

// The library's folders (design/library-setup.md): the setup wizard's library step and
// Settings choose them; the backend checks them (POST /library/inspect) before they're applied.

handleTrusted('library:get-dirs', () => {
  const defaults = getDefaultDirs()
  const dirs = currentDirs ?? { ...defaults, linked: null }
  return { ...dirs, defaults }
})

handleTrusted('library:choose-folder', (event, kind, current) => {
  if (!isFolderKind(kind)) throw new Error('Invalid folder kind')
  const start = isAbsolutePath(current) ? current : (currentDirs?.[kind] ?? undefined)
  return pickLibraryFolder(event.sender, kind, start)
})

// Resolves only when the folders are rejected or nothing changed. Otherwise the backend
// restarts on the new folders in this window, which then loads the UI afresh.
handleTrusted('library:apply', (_event, raw) => {
  // A second click while the window is already restarting.
  if (restarting) return new Promise(() => {})
  const parsed = parseLibraryDirs(raw)
  if ('error' in parsed) return { error: parsed.error, restarted: false }
  const next = parsed.dirs
  const config = loadConfig()
  if (!config) return { error: "Couldn't read the app's settings file.", restarted: false }

  // The backend refuses to start unless both roots already exist. The linked folder is
  // never created or written: it may be offline, and the backend reports that.
  const dirError = unavailableLinkedError(next) ?? prepareStorageDirs(next.appData, next.store)
  if (dirError) return { error: dirError, restarted: false }

  const current = currentDirs ?? libraryDirsOf(config)
  const changed = dirsChanged(current, next)
  const replaced =
    config.provisional && changed ? provisionalDirsToDelete(current, next, getDefaultDirs()) : []
  saveConfig(withChosenLibrary(config, next))
  if (!changed) return { error: null, restarted: false }

  if (isDev) {
    // No sidecar to restart: the developer's backend keeps its own folders.
    currentDirs = next
    console.warn(
      '[electron] Library folders saved to the config; the dev backend ignores them. ' +
        'Restart it with SCENE_ATLAS_DATA_DIR, SCENE_ATLAS_IMAGES_DIR and SCENE_ATLAS_LINKED_LIBRARY_DIR to use them.',
    )
    return { error: null, restarted: false }
  }

  restartBackend(next, replaced)
  return new Promise(() => {})
})

// Settings that apply only on a restart: the same in-window restart, on the folders in use.
// Resolves false in dev, where there's no sidecar to restart; otherwise never (the page is
// replaced).
handleTrusted('app:restart-backend', () => {
  if (isDev || !currentDirs) return false
  if (!restarting) restartBackend(currentDirs)
  return new Promise(() => {})
})

// Updates (design/electron.md#updates)

handleTrusted('updates:get-state', () => updater?.getState() ?? null)
handleTrusted('updates:check', () => updater?.check() ?? null)
handleTrusted('updates:set-choice', (_event, raw) => {
  const choice = parseUpdateChoice(raw)
  if (!choice || !updater) return updater?.getState() ?? null
  updateConfig({ updateChoice: choice })
  return updater.setChoice(choice)
})
handleTrusted('updates:download', () => updater?.download() ?? null)
// Doesn't resolve when the installer starts: the app quits.
handleTrusted('updates:install', () => updater?.install())
handleTrusted('updates:open-download', () => updater?.openDownload())

function broadcastUpdateState(state: UpdateState): void {
  for (const win of BrowserWindow.getAllWindows()) {
    if (!win.isDestroyed()) win.webContents.send('updates:state', state)
  }
}

function startUpdater(): void {
  const logPath = path.join(app.getPath('userData'), 'updater.log')
  rotateLog(logPath)
  updater = new Updater({
    choice: loadConfig()?.updateChoice ?? null,
    logPath,
    stopBackend: () => stopSidecar(QUIT_GRACE_MS),
    onChange: broadcastUpdateState,
  })
  updater.start()
}

// Windows

function createMainWindow(): BrowserWindow {
  const placement = mainWindowPlacement()
  const win = new BrowserWindow({
    ...placement.bounds,
    ...frameOptions(),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  })
  if (placement.maximized) win.maximize()

  hardenWindow(win)
  removeMenu(win)
  rememberWindowState(win)

  win.webContents.on('did-finish-load', () => {
    if (backendError !== null) sendBackendError(win)
  })

  if (isDev) {
    win.loadURL(DEV_SERVER_URL)
    win.webContents.openDevTools()
  } else {
    // Shown until the sidecar is up; then the window navigates to the UI it serves.
    win.loadFile(LOADING_PAGE)
  }

  win.on('closed', () => {
    mainWindow = null
  })
  return win
}

async function waitForHealth(origin: string, timeoutMs = 120_000): Promise<boolean> {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    try {
      if ((await fetch(`${origin}/health`)).ok) return true
    } catch {
      // Not accepting connections yet.
    }
    await new Promise((resolve) => setTimeout(resolve, 100))
  }
  return false
}

async function showBackendUi(port: number, child: ChildProcess): Promise<void> {
  const origin = `http://127.0.0.1:${port}`
  const healthy = await waitForHealth(origin)
  // It exited or was replaced meanwhile, and whatever did that has reported it.
  if (child !== sidecarProcess) return
  if (!healthy) {
    signalBackendError(`The backend did not respond on ${origin}.`)
    return
  }
  backendOrigin = origin
  await mainWindow?.loadURL(`${origin}/`)
}

function signalBackendError(message: string, aboutFolders = false): void {
  backendError = message
  backendErrorIsFolders = aboutFolders
  const win = mainWindow
  if (!win) return
  // A crash after startup leaves the UI on a dead origin; go back to the loading page,
  // which receives the error on did-finish-load.
  if (win.webContents.getURL().startsWith('file:')) sendBackendError(win)
  else void win.loadFile(LOADING_PAGE)
}

/** The loading page offers Choose folders… (design/library-setup.md §3.3). */
function canChooseFoldersAgain(): boolean {
  // Choosing folders again means the defaults, so it can't help when those were refused.
  const defaults = { ...getDefaultDirs(), linked: null }
  return (
    backendError !== null &&
    backendErrorIsFolders &&
    currentDirs !== null &&
    dirsChanged(currentDirs, defaults)
  )
}

function sendBackendError(win: BrowserWindow): void {
  const chooseFolders = canChooseFoldersAgain()
  win.webContents.send('backend-error', backendError, { chooseFolders, retry: !isDev })
}

// Backend sidecar

function rotateLog(logPath: string): void {
  try {
    if (fs.statSync(logPath).size > MAX_LOG_BYTES) {
      fs.renameSync(logPath, `${logPath}.1`)
    }
  } catch {
    // No log yet, or rotation failed: keep appending to the current file.
  }
}

function launchApp(dirs: LibraryDirs): void {
  mainWindow = createMainWindow()
  void startBackend(dirs)
}

/** Start the sidecar on *dirs*; the main window shows its UI once it is ready. */
async function startBackend(dirs: LibraryDirs): Promise<void> {
  currentDirs = dirs
  backendOrigin = null
  backendError = null
  backendErrorIsFolders = false

  // Dev: the developer runs the backend themselves; Vite proxies /api to it.
  if (isDev) return

  const { appData: appDataDir, store: imageLibraryDir, linked: linkedLibraryDir } = dirs
  // A config-loaded start can point at a drive that is no longer mounted.
  const dirError = unavailableLinkedError(dirs) ?? prepareStorageDirs(appDataDir, imageLibraryDir)
  if (dirError) {
    signalBackendError(dirError, true)
    return
  }

  let port: number
  try {
    port = await findFreePort(PREFERRED_PORT)
  } catch (err) {
    console.error('Failed to find a free port:', err)
    signalBackendError('Could not find a free port')
    return
  }
  // Closed meanwhile (macOS keeps running): nothing would stop this backend.
  if (!mainWindow) return

  // Sidecar output goes to a log file to help diagnose startup crashes.
  const logPath = path.join(app.getPath('userData'), 'backend.log')
  rotateLog(logPath)
  const logStream = fs.createWriteStream(logPath, { flags: 'a' })
  const writeLog = (text: string) => {
    if (!logStream.writableEnded) logStream.write(text)
  }
  const closeLog = () => {
    if (!logStream.writableEnded) logStream.end()
  }
  writeLog(`\n--- Scene Atlas started ${new Date().toISOString()} ---\n`)
  const folders = `appData=${appDataDir} imageLibrary=${imageLibraryDir} linked=${linkedLibraryDir ?? '-'}`
  writeLog(`port=${port} ${folders}\n`)
  console.log(`[electron] Spawning backend on port ${port}, ${folders}`)
  console.log(`[electron] Sidecar log: ${logPath}`)

  // Recent output lines are shown in the error screen.
  const recentLines: string[] = []
  const logLine = (line: string) => {
    console.log(line)
    writeLog(line + '\n')
    recentLines.push(line)
    if (recentLines.length > 50) recentLines.shift()
  }

  let ready = false
  const child = spawnSidecar({
    port,
    appDataDir,
    imageLibraryDir,
    linkedLibraryDir,
    onReady: (readyPort) => {
      ready = true
      console.log(`[electron] Backend ready on port ${readyPort}`)
      void showBackendUi(readyPort, child)
    },
    onLog: logLine,
    onError: (message) => {
      // 'exit' may or may not follow a spawn error; detach so it doesn't overwrite this message.
      if (sidecarProcess === child) sidecarProcess = null
      closeLog()
      signalBackendError(`Could not start the backend: ${message}\n\nFull log: ${logPath}`)
    },
  })

  sidecarProcess = child

  child.on('exit', (code, signal) => {
    writeLog(`--- exited code=${code} signal=${signal} ---\n`)
    closeLog()
    // stopSidecar() clears sidecarProcess first, so an intentional stop is not reported.
    if (child !== sidecarProcess) return
    sidecarProcess = null
    // Before ready, any exit is a startup failure (even code 0). After ready, only a
    // non-zero code is a crash.
    if (ready && (code === 0 || code === null)) return
    const tail = recentLines.slice(-10).join('\n')
    const what = ready ? 'Backend crashed' : 'Backend exited during startup'
    signalBackendError(
      `${what} (exit code ${code ?? signal}).\n\nLast output:\n${tail}\n\nFull log: ${logPath}`,
      !ready && code === LIBRARY_REFUSED,
    )
  })
}

/**
 * Ask the sidecar to shut down; resolves when it exits or after timeoutMs. Past the
 * timeout it is killed on Windows (where kill() terminates outright, so it is only the
 * fallback) or, with *force*, everywhere, and waited for a little longer.
 */
function stopSidecar(timeoutMs = 5000, force = false): Promise<void> {
  const child = sidecarProcess
  sidecarProcess = null
  if (!child || child.exitCode !== null || child.signalCode !== null) return Promise.resolve()
  console.log('[electron] Stopping backend sidecar')
  return new Promise((resolve) => {
    let killTimer: NodeJS.Timeout | undefined
    const timer = setTimeout(() => {
      if (!(isWindows || force) || child.exitCode !== null) {
        resolve()
        return
      }
      child.kill('SIGKILL')
      killTimer = setTimeout(resolve, 2000)
    }, timeoutMs)
    child.once('exit', () => {
      clearTimeout(timer)
      clearTimeout(killTimer)
      resolve()
    })
    // Closing stdin makes the sidecar's watchdog shut down gracefully on every platform.
    child.stdin?.end()
    if (!isWindows) child.kill('SIGTERM')
  })
}

// The loading page's actions after a startup failure (design/library-setup.md §3.3).
// Each acts only while the page offers it.

handleTrusted('startup:retry', () => {
  if (restarting || !currentDirs || isDev || backendError === null) return
  restartBackend(currentDirs)
})

// Back to the default folders, with the setup wizard's library step to choose the real
// ones. The refused folders are left exactly as they are.
handleTrusted('startup:choose-folders', () => {
  const config = loadConfig()
  if (restarting || !config || isDev || !canChooseFoldersAgain()) return
  const next = onDefaultFolders(config)
  saveConfig(next)
  restartBackend(libraryDirsOf(next))
})

/**
 * Swap the backend for one on *dirs* without closing the window (design/library-setup.md
 * §2.2): the loading page while the old backend stops and the new one starts, then the UI
 * it serves. *replacedProvisional* are first-launch folders the new ones replace.
 */
function restartBackend(dirs: LibraryDirs, replacedProvisional: string[] = []): void {
  restarting = (async () => {
    const win = mainWindow
    backendError = null
    await win?.loadFile(LOADING_PAGE).catch(() => {})
    backendOrigin = null
    // Forced past the grace period: the new backend may need the same folders' locks.
    await stopSidecar(QUIT_GRACE_MS, true)
    await removeProvisionalDirs(replacedProvisional, getDefaultDirs())
    // Closed meanwhile (macOS keeps running): activate starts the next window's backend.
    if (win && mainWindow === win) await startBackend(dirs)
  })()
    .catch((err: unknown) => signalBackendError(`Could not restart the backend: ${String(err)}`))
    .finally(() => {
      restarting = null
    })
}

// Lifecycle

/** *config* (or, on a first launch, a new one) on the default folders, not yet chosen. */
function onDefaultFolders(config: AppConfig | null): AppConfig {
  const defaults = getDefaultDirs()
  const empty = isMissingOrEmpty(defaults.appData) && isMissingOrEmpty(defaults.store)
  return config ? withDefaultLibrary(config, defaults, empty) : firstLaunchConfig(defaults, empty)
}

function start(): void {
  let config = loadConfig()
  if (!config) {
    // First launch: a library on the default folders, so the backend (and the setup
    // wizard it serves) can start. The wizard's library step can replace them.
    const aside = setAsideUnusableConfig()
    if (aside) console.warn(`[electron] Config couldn't be read; moved to ${aside}`)
    config = onDefaultFolders(null)
    saveConfig(config)
  }
  // Every window, including the loading page, follows the UI's theme choice
  nativeTheme.themeSource = themeSourceFor(config.displayPrefs ?? {})
  launchApp(libraryDirsOf(config))
}

app.on('second-instance', () => {
  const win = mainWindow
  if (!win) return
  if (win.isMinimized()) win.restore()
  win.focus()
})

app.whenReady().then(() => {
  if (!hasInstanceLock) return
  setMacMenu()
  startUpdater()
  start()
})

app.on('window-all-closed', () => {
  // macOS keeps the app in the dock without a backend; activate starts a new one.
  if (isMac) void stopSidecar()
  else app.quit()
})

app.on('activate', () => {
  if (!hasInstanceLock) return
  // After a restart whose window was closed: its old backend may still hold the folders.
  void Promise.resolve(restarting).then(() => {
    if (BrowserWindow.getAllWindows().length === 0) start()
  })
})

// Hold the quit until the backend has shut down. On Windows this is what makes the stop
// graceful at all: libuv puts spawned children in a kill-on-close job object, so the
// sidecar is terminated the moment this process exits, mid-shutdown if still running.
let quitting = false
app.on('will-quit', (event) => {
  if (quitting || !sidecarProcess) return
  event.preventDefault()
  quitting = true
  void stopSidecar(QUIT_GRACE_MS).finally(() => app.quit())
})
