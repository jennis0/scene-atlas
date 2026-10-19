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
import { getDefaultDirs, loadConfig, saveConfig, updateConfig } from './config'
import {
  isDisplayPref,
  sanitizeWindowColors,
  themeSourceFor,
  THEME_PREF_KEY,
  withDisplayPref,
} from './displayPrefs'
import { hasForeignEntries, prepareStorageDirs } from './storageDirs'
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

let mainWindow: BrowserWindow | null = null
let setupWindow: BrowserWindow | null = null
let sidecarProcess: ChildProcess | null = null
let currentAppDataDir: string | null = null
let currentImageLibraryDir: string | null = null

// The packaged UI is served by the sidecar, so its origin is the backend's.
let backendOrigin: string | null = null
// Kept so the loading page can be re-sent the error after a reload.
let backendError: string | null = null

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

type StorageKind = 'appData' | 'imageLibrary'

const STORAGE_PICKER: Record<StorageKind, { title: string; foreignDetail: string }> = {
  appData: {
    title: 'Choose App Data Folder',
    foreignDetail:
      'Scene Atlas keeps its database, thumbnails and search index here. ' +
      'A new or empty folder keeps them apart from your other files.',
  },
  imageLibrary: {
    title: 'Choose Image Library Folder',
    foreignDetail:
      'Scene Atlas keeps its own copy of every image you import here, in its own ' +
      'folder layout. It will not show the files already in this folder: bring ' +
      'your existing maps in with Import instead.\n\nA new or empty folder is best.',
  },
}

/** Pick a storage folder, warning when it already holds files Scene Atlas didn't create
 * (most likely the user's existing collection, design/electron.md). Null when cancelled. */
async function pickStorageDir(
  win: BrowserWindow | null,
  kind: StorageKind,
  defaultPath?: string,
  otherRoot?: string,
): Promise<string | null> {
  const { title, foreignDetail } = STORAGE_PICKER[kind]
  for (;;) {
    const chosen = await pickDirectory(win, title, defaultPath)
    if (!chosen || !hasForeignEntries(chosen, otherRoot)) return chosen
    const options: Electron.MessageBoxOptions = {
      type: 'warning',
      title: 'Folder is not empty',
      message: 'This folder already has other files in it.',
      detail: foreignDetail,
      buttons: ['Choose Another Folder', 'Use This Folder'],
      defaultId: 0,
      cancelId: 0,
      noLink: true,
    }
    const { response } = win
      ? await dialog.showMessageBox(win, options)
      : await dialog.showMessageBox(options)
    if (response === 1) return chosen
    defaultPath = chosen
  }
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

// Display choices (design/first-run.md): the UI keeps them in the config as well as its
// localStorage, which is tied to the backend's port. Synchronous on purpose: the preload
// needs them before the page's first paint.
ipcMain.on('prefs:get-sync', (event) => {
  try {
    assertTrusted(event)
    event.returnValue = loadConfig()?.displayPrefs ?? {}
  } catch {
    event.returnValue = {}
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

handleTrusted('setup:get-default-dirs', () => getDefaultDirs())

handleTrusted('setup:choose-directory', (event, kind, currentDir, otherRoot) => {
  if (kind !== 'appData' && kind !== 'imageLibrary') throw new Error('Invalid storage kind')
  return pickStorageDir(
    BrowserWindow.fromWebContents(event.sender),
    kind,
    isAbsolutePath(currentDir) ? currentDir : undefined,
    isAbsolutePath(otherRoot) ? otherRoot : undefined,
  )
})

// Synchronous on purpose: mainWindow is assigned before this returns, so a
// second invocation (double-click) sees it and can't spawn a second sidecar.
handleTrusted('setup:complete', (_event, appDataDir, imageLibraryDir) => {
  if (mainWindow) return { error: null }
  if (!isAbsolutePath(appDataDir) || !isAbsolutePath(imageLibraryDir)) {
    return { error: 'Both locations must be absolute folder paths.' }
  }

  // The backend refuses to start unless both roots already exist.
  const dirError = prepareStorageDirs(appDataDir, imageLibraryDir)
  if (dirError) return { error: dirError }

  saveConfig({ appDataDir, imageLibraryDir })
  void launchApp(appDataDir, imageLibraryDir)
  setupWindow?.close()
  return { error: null }
})

handleTrusted('imports:choose-folders', (event) =>
  pickImportPaths(BrowserWindow.fromWebContents(event.sender), 'folders'),
)
handleTrusted('imports:choose-files', (event) =>
  pickImportPaths(BrowserWindow.fromWebContents(event.sender), 'files'),
)

handleTrusted('system:get-app-data-dir', () => currentAppDataDir)
handleTrusted('system:get-image-library-dir', () => currentImageLibraryDir)

handleTrusted('system:choose-app-data-dir', (event) =>
  pickStorageDir(
    BrowserWindow.fromWebContents(event.sender),
    'appData',
    currentAppDataDir ?? getDefaultDirs().appDataDir,
    currentImageLibraryDir ?? undefined,
  ),
)

handleTrusted('system:choose-image-library-dir', (event) =>
  pickStorageDir(
    BrowserWindow.fromWebContents(event.sender),
    'imageLibrary',
    currentImageLibraryDir ?? getDefaultDirs().imageLibraryDir,
    currentAppDataDir ?? undefined,
  ),
)

// Saves new paths to config and restarts.
// Called only when user explicitly clicks "Restart Now" in the Settings UI.
handleTrusted('system:change-storage-dirs', async (_event, newAppDataDir, newImageLibraryDir) => {
  if (!isAbsolutePath(newAppDataDir) || !isAbsolutePath(newImageLibraryDir)) {
    return { error: 'Both locations must be absolute folder paths.' }
  }
  const dirError = prepareStorageDirs(newAppDataDir, newImageLibraryDir)
  if (dirError) return { error: dirError }

  saveConfig({ ...loadConfig(), appDataDir: newAppDataDir, imageLibraryDir: newImageLibraryDir })
  // app.exit() skips will-quit, so stop the old backend explicitly; otherwise it
  // keeps running against the old store while the relaunched app starts a new one.
  await stopSidecar()
  app.relaunch()
  app.exit(0)
  return { error: null }
})

// Windows

function showSetupWindow(): void {
  setupWindow = new BrowserWindow({
    width: 600,
    height: 640,
    resizable: true,
    minWidth: 520,
    minHeight: 560,
    ...frameOptions(),
    webPreferences: {
      preload: path.join(__dirname, 'setup.preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  })

  hardenWindow(setupWindow)
  removeMenu(setupWindow)
  setupWindow.loadFile(path.join(__dirname, '..', 'setup.html'))

  setupWindow.on('closed', () => {
    setupWindow = null
    if (!mainWindow) app.quit()
  })
}

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
    if (backendError !== null) win.webContents.send('backend-error', backendError)
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

function signalBackendError(message: string): void {
  backendError = message
  const win = mainWindow
  if (!win) return
  // A crash after startup leaves the UI on a dead origin; go back to the loading page,
  // which receives the error on did-finish-load.
  if (win.webContents.getURL().startsWith('file:')) win.webContents.send('backend-error', message)
  else void win.loadFile(LOADING_PAGE)
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

async function launchApp(appDataDir: string, imageLibraryDir: string): Promise<void> {
  currentAppDataDir = appDataDir
  currentImageLibraryDir = imageLibraryDir
  backendOrigin = null
  backendError = null
  mainWindow = createMainWindow()

  // Dev: the developer runs the backend themselves; Vite proxies /api to it.
  if (isDev) return

  // A config-loaded start can point at a drive that is no longer mounted.
  const dirError = prepareStorageDirs(appDataDir, imageLibraryDir)
  if (dirError) {
    signalBackendError(dirError)
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
  writeLog(`port=${port} appData=${appDataDir} imageLibrary=${imageLibraryDir}\n`)
  console.log(
    `[electron] Spawning backend on port ${port}, appData=${appDataDir}, imageLibrary=${imageLibraryDir}`,
  )
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
    )
  })
}

/** Ask the sidecar to shut down; resolves when it exits or after timeoutMs. */
function stopSidecar(timeoutMs = 5000): Promise<void> {
  const child = sidecarProcess
  sidecarProcess = null
  if (!child || child.exitCode !== null || child.signalCode !== null) return Promise.resolve()
  console.log('[electron] Stopping backend sidecar')
  return new Promise((resolve) => {
    const timer = setTimeout(() => {
      // On Windows kill() terminates outright, so it is only the fallback there.
      if (isWindows && child.exitCode === null) child.kill()
      resolve()
    }, timeoutMs)
    child.once('exit', () => {
      clearTimeout(timer)
      resolve()
    })
    // Closing stdin makes the sidecar's watchdog shut down gracefully on every platform.
    child.stdin?.end()
    if (!isWindows) child.kill('SIGTERM')
  })
}

// Lifecycle

function start(): void {
  const config = loadConfig()
  // Every window, including the loading page, follows the UI's theme choice
  nativeTheme.themeSource = themeSourceFor(config?.displayPrefs ?? {})
  if (config) {
    void launchApp(config.appDataDir, config.imageLibraryDir)
  } else {
    showSetupWindow()
  }
}

app.on('second-instance', () => {
  const win = mainWindow ?? setupWindow
  if (!win) return
  if (win.isMinimized()) win.restore()
  win.focus()
})

app.whenReady().then(() => {
  if (!hasInstanceLock) return
  setMacMenu()
  start()
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
