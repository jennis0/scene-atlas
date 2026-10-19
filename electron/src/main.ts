import {
  app,
  BrowserWindow,
  dialog,
  ipcMain,
  IpcMainInvokeEvent,
  nativeTheme,
  shell,
} from 'electron'
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
  unavailableLinkedError,
  type FolderKind,
  type LibraryDirs,
} from './libraryDirs'
import { hasForeignEntries, prepareStorageDirs } from './storageDirs'

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

let mainWindow: BrowserWindow | null = null
let sidecarProcess: ChildProcess | null = null
// The folders the backend runs on (in dev, the config's: the developer runs the backend).
let currentDirs: LibraryDirs | null = null
// Set while restartBackend() swaps the backend for one on other folders.
let restarting = false

// The packaged UI is served by the sidecar, so its origin is the backend's.
let backendOrigin: string | null = null
// Kept so the loading page can be re-sent the error after a reload.
let backendError: string | null = null
// The failure is about the folders (refused by the library check, or unusable), so the
// loading page also offers to choose them again (design/library-setup.md §3.3).
let backendErrorIsFolders = false

// The backend's exit code when its library check refused the folders (pyinstaller/entry.py)
const LIBRARY_REFUSED = 4

// The installer's shortcuts carry electron-builder's appId as their AppUserModelID; the
// process must match, or Windows shows a pinned shortcut and the running app as two
// taskbar icons.
if (isWindows) app.setAppUserModelId('com.sceneatlas.app')

// Two instances would run two backends against one SQLite/LanceDB store.
const hasInstanceLock = app.requestSingleInstanceLock()
if (!hasInstanceLock) {
  app.quit()
}

// Window helpers

/** The colours a new window starts in: the UI's last reported ones, else the navy palette's
 * page background and text (frontend/src/index.css) for the current light/dark. */
function windowColors(): { background: string; foreground: string } {
  const saved = loadConfig()?.windowColors
  if (saved) return saved
  return nativeTheme.shouldUseDarkColors
    ? { background: '#0e1118', foreground: '#ede8dc' }
    : { background: '#eee9e2', foreground: '#2b2622' }
}

/** Borderless window config: hiddenInset on macOS, hidden + overlay on Win/Linux. */
function borderlessOptions(): Partial<Electron.BrowserWindowConstructorOptions> {
  const { background, foreground } = windowColors()
  return {
    backgroundColor: background,
    titleBarStyle: isMac ? 'hiddenInset' : 'hidden',
    ...(!isMac && {
      titleBarOverlay: {
        color: background,
        symbolColor: foreground,
        height: 32,
      },
    }),
  }
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

async function pickDirectory(
  win: BrowserWindow | null,
  title: string,
  defaultPath?: string,
): Promise<string | null> {
  const options: Electron.OpenDialogOptions = {
    title,
    // Electron 43+ opens dialogs in Downloads unless given a starting folder.
    defaultPath: defaultPath ?? app.getPath('home'),
    properties: ['openDirectory', 'createDirectory'],
    buttonLabel: 'Select Folder',
  }
  const result = win
    ? await dialog.showOpenDialog(win, options)
    : await dialog.showOpenDialog(options)
  return result.canceled ? null : result.filePaths[0]
}

const FOLDER_PICKER_TITLES: Record<FolderKind, string> = {
  appData: 'Choose Search Data Folder',
  store: 'Choose Imported Maps Folder',
  linked: 'Choose Your Maps Folder',
}

/** Files and folders to import (design/local-ingest.md). Empty when cancelled. */
async function pickImportPaths(win: BrowserWindow | null, kind: 'folders' | 'files') {
  const options: Electron.OpenDialogOptions =
    kind === 'folders'
      ? { title: 'Import folders', properties: ['openDirectory', 'multiSelections'] }
      : {
          title: 'Import files',
          properties: ['openFile', 'multiSelections'],
          filters: [{ name: 'Images, videos and zips', extensions: IMPORT_EXTENSIONS }],
        }
  options.buttonLabel = 'Import'
  const result = win
    ? await dialog.showOpenDialog(win, options)
    : await dialog.showOpenDialog(options)
  return result.canceled ? [] : result.filePaths
}

const IMPORT_EXTENSIONS = ['jpg', 'jpeg', 'png', 'webp', 'mp4', 'webm', 'zip']

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

function isAbsolutePath(value: unknown): value is string {
  return typeof value === 'string' && value.trim() !== '' && path.isAbsolute(value)
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
  win.setBackgroundColor(colors.background)
  if (!isMac) win.setTitleBarOverlay({ color: colors.background, symbolColor: colors.foreground })
  const saved = loadConfig()?.windowColors
  if (saved?.background !== colors.background || saved?.foreground !== colors.foreground) {
    updateConfig({ windowColors: colors })
  }
})

handleTrusted('imports:choose-folders', (event) =>
  pickImportPaths(BrowserWindow.fromWebContents(event.sender), 'folders'),
)
handleTrusted('imports:choose-files', (event) =>
  pickImportPaths(BrowserWindow.fromWebContents(event.sender), 'files'),
)

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
  return pickDirectory(
    BrowserWindow.fromWebContents(event.sender),
    FOLDER_PICKER_TITLES[kind],
    start,
  )
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
  const replaced = config.provisional && changed ? provisionalDirsToDelete(current, next) : []
  saveConfig(withChosenLibrary(config, next))
  if (!changed) return { error: null, restarted: false }

  if (isDev) {
    // No sidecar to restart: the developer's backend keeps its own folders.
    currentDirs = next
    console.warn(
      '[electron] Library folders saved to the config; the dev backend ignores them. ' +
        'Restart it with APP_DATA_DIR, IMAGE_LIBRARY_DIR and LINKED_LIBRARY_DIR to use them.',
    )
    return { error: null, restarted: false }
  }

  void restartBackend(next, replaced)
  return new Promise(() => {})
})

// Windows

function createMainWindow(): BrowserWindow {
  const win = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 900,
    minHeight: 600,
    ...borderlessOptions(),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  })

  hardenWindow(win)

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

async function showBackendUi(port: number): Promise<void> {
  const origin = `http://127.0.0.1:${port}`
  if (!(await waitForHealth(origin))) {
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

function sendBackendError(win: BrowserWindow): void {
  // Choosing folders again means the defaults, so it can't help when those were refused.
  const defaults = { ...getDefaultDirs(), linked: null }
  const chooseFolders =
    backendErrorIsFolders && currentDirs !== null && dirsChanged(currentDirs, defaults)
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
  backendOrigin = null
  backendError = null
  backendErrorIsFolders = false
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
      void showBackendUi(readyPort)
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

// The loading page's actions after a startup failure (design/library-setup.md §3.3)

handleTrusted('startup:retry', () => {
  if (restarting || !currentDirs || isDev) return
  void restartBackend(currentDirs, [])
})

// Back to the default folders, with the setup wizard's library step to choose the real
// ones. The refused folders are left exactly as they are.
handleTrusted('startup:choose-folders', () => {
  const config = loadConfig()
  if (restarting || !config || isDev) return
  const defaults = getDefaultDirs()
  const empty = isMissingOrEmpty(defaults.appData) && isMissingOrEmpty(defaults.store)
  const next = withDefaultLibrary(config, defaults, empty)
  saveConfig(next)
  void restartBackend(libraryDirsOf(next), [])
})

/**
 * Swap the backend for one on *dirs* without closing the window (design/library-setup.md
 * §2.2): the loading page while the old backend stops and the new one starts, then the UI
 * it serves. *replacedProvisional* are first-launch folders the new ones replace.
 */
async function restartBackend(dirs: LibraryDirs, replacedProvisional: string[]): Promise<void> {
  restarting = true
  try {
    const win = mainWindow
    backendError = null
    await win?.loadFile(LOADING_PAGE).catch(() => {})
    backendOrigin = null
    // Forced past the grace period: the new backend may need the same folders' locks.
    await stopSidecar(QUIT_GRACE_MS, true)
    await removeProvisionalDirs(replacedProvisional)
    // Closed meanwhile (macOS keeps running): the next window starts its own backend.
    if (!win || mainWindow !== win) return
    await startBackend(dirs)
  } finally {
    restarting = false
  }
}

/**
 * Delete first-launch folders the user replaced in setup. Nothing can have been imported
 * into them (the gallery is gated until setup is complete), and each is kept if it holds
 * anything Scene Atlas didn't create.
 */
async function removeProvisionalDirs(dirs: string[]): Promise<void> {
  const defaultBase = path.dirname(getDefaultDirs().appData)
  for (const dir of dirs) {
    if (hasForeignEntries(dir)) {
      console.log(`[electron] Keeping ${dir}: it holds other files`)
      continue
    }
    // Windows can hold the stopped backend's files open for a moment.
    for (let attempt = 1; ; attempt++) {
      try {
        fs.rmSync(dir, { recursive: true, force: true })
        break
      } catch (err) {
        if (attempt === 5) {
          console.warn(`[electron] Couldn't delete ${dir}:`, err)
          break
        }
        await new Promise((resolve) => setTimeout(resolve, 500))
      }
    }
    // The "Scene Atlas" folder the defaults sit in, once nothing is left in it.
    if (path.dirname(dir) === defaultBase) {
      try {
        fs.rmdirSync(defaultBase) // only succeeds when empty
      } catch {
        // Something else is in it, or it's gone already.
      }
    }
  }
}

// Lifecycle

function start(): void {
  let config = loadConfig()
  if (!config) {
    // First launch: a library on the default folders, so the backend (and the setup
    // wizard it serves) can start. The wizard's library step can replace them.
    const aside = setAsideUnusableConfig()
    if (aside) console.warn(`[electron] Config couldn't be read; moved to ${aside}`)
    const defaults = getDefaultDirs()
    const empty = isMissingOrEmpty(defaults.appData) && isMissingOrEmpty(defaults.store)
    config = firstLaunchConfig(defaults, empty)
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
  if (hasInstanceLock) start()
})

app.on('window-all-closed', () => {
  // macOS keeps the app in the dock without a backend; activate starts a new one.
  if (isMac) void stopSidecar()
  else app.quit()
})

app.on('activate', () => {
  if (hasInstanceLock && BrowserWindow.getAllWindows().length === 0) start()
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
