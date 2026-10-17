import { app, BrowserWindow, dialog, ipcMain, IpcMainInvokeEvent, shell } from 'electron'
import * as fs from 'fs'
import * as path from 'path'
import { ChildProcess } from 'child_process'
import { findFreePort, spawnSidecar } from './sidecar'
import { getDefaultDirs, loadConfig, saveConfig } from './config'

const isDev = !app.isPackaged
const isMac = process.platform === 'darwin'
const DEV_SERVER_URL = 'http://localhost:5173'
const DEV_BACKEND_PORT = 8000
const MAX_LOG_BYTES = 5 * 1024 * 1024

let mainWindow: BrowserWindow | null = null
let setupWindow: BrowserWindow | null = null
let sidecarProcess: ChildProcess | null = null
let currentAppDataDir: string | null = null
let currentImageLibraryDir: string | null = null
let currentConvertToWebp = false

// Kept so a renderer reload (or a page that finishes loading after the signal)
// can be re-sent the current backend state on did-finish-load.
let backendPort: number | null = null
let backendError: string | null = null

// Two instances would run two backends against one SQLite/LanceDB store.
const hasInstanceLock = app.requestSingleInstanceLock()
if (!hasInstanceLock) {
  app.quit()
}

// Window helpers

/** Borderless titlebar config: hiddenInset on macOS, hidden + overlay on Win/Linux. */
function borderlessOptions(): Partial<Electron.BrowserWindowConstructorOptions> {
  return {
    titleBarStyle: isMac ? 'hiddenInset' : 'hidden',
    ...(!isMac && {
      titleBarOverlay: {
        color: '#0e1118',
        symbolColor: '#ede8dc',
        height: 32,
      },
    }),
  }
}

/** True for pages that belong to the app: the Vite dev server in dev, file:// when packaged. */
function isAppUrl(url: string): boolean {
  try {
    const parsed = new URL(url)
    if (parsed.protocol === 'file:') return true
    return isDev && parsed.origin === new URL(DEV_SERVER_URL).origin
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
    defaultPath,
    properties: ['openDirectory', 'createDirectory'],
    buttonLabel: 'Select Folder',
  }
  const result = win
    ? await dialog.showOpenDialog(win, options)
    : await dialog.showOpenDialog(options)
  return result.canceled ? null : result.filePaths[0]
}

// IPC

function assertTrusted(event: IpcMainInvokeEvent): void {
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

/** Create both storage roots and check they are writable. Returns an error message or null. */
function prepareStorageDirs(appDataDir: string, imageLibraryDir: string): string | null {
  const dirs: [string, string][] = [
    ['App data directory', appDataDir],
    ['Image library directory', imageLibraryDir],
  ]
  for (const [label, dir] of dirs) {
    try {
      fs.mkdirSync(dir, { recursive: true })
      const testFile = path.join(dir, `.write-test-${Date.now()}`)
      fs.writeFileSync(testFile, 'test')
      fs.unlinkSync(testFile)
    } catch (err) {
      return `${label} is not usable: ${dir}\n${(err as Error).message}`
    }
  }
  return null
}

handleTrusted('setup:get-default-dirs', () => getDefaultDirs())

handleTrusted('setup:choose-directory', (event) =>
  pickDirectory(BrowserWindow.fromWebContents(event.sender), 'Choose Folder'),
)

// Synchronous on purpose: mainWindow is assigned before this returns, so a
// second invocation (double-click) sees it and can't spawn a second sidecar.
handleTrusted('setup:complete', (_event, appDataDir, imageLibraryDir, convertToWebp) => {
  if (mainWindow) return { error: null }
  if (!isAbsolutePath(appDataDir) || !isAbsolutePath(imageLibraryDir)) {
    return { error: 'Both locations must be absolute folder paths.' }
  }
  if (typeof convertToWebp !== 'boolean') {
    return { error: 'Invalid WebP setting.' }
  }

  // The backend refuses to start unless both roots already exist.
  const dirError = prepareStorageDirs(appDataDir, imageLibraryDir)
  if (dirError) return { error: dirError }

  saveConfig({ appDataDir, imageLibraryDir, convertToWebp })
  void launchApp(appDataDir, imageLibraryDir, convertToWebp)
  setupWindow?.close()
  return { error: null }
})

handleTrusted('system:get-app-data-dir', () => currentAppDataDir)
handleTrusted('system:get-image-library-dir', () => currentImageLibraryDir)

handleTrusted('system:choose-app-data-dir', (event) =>
  pickDirectory(
    BrowserWindow.fromWebContents(event.sender),
    'Choose App Data Location',
    currentAppDataDir ?? getDefaultDirs().appDataDir,
  ),
)

handleTrusted('system:choose-image-library-dir', (event) =>
  pickDirectory(
    BrowserWindow.fromWebContents(event.sender),
    'Choose Image Library Location',
    currentImageLibraryDir ?? getDefaultDirs().imageLibraryDir,
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

  saveConfig({
    appDataDir: newAppDataDir,
    imageLibraryDir: newImageLibraryDir,
    convertToWebp: currentConvertToWebp,
  })
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
    backgroundColor: '#0e1118',
    ...borderlessOptions(),
    webPreferences: {
      preload: path.join(__dirname, 'setup.preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  })

  hardenWindow(setupWindow)
  setupWindow.loadFile(path.join(__dirname, '..', 'setup.html'))

  setupWindow.on('closed', () => {
    setupWindow = null
    if (!mainWindow) app.quit()
  })
}

function createMainWindow(): BrowserWindow {
  const win = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 900,
    minHeight: 600,
    backgroundColor: '#0e1118',
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
    if (backendPort !== null) win.webContents.send('backend-ready', backendPort)
    if (backendError !== null) win.webContents.send('backend-error', backendError)
  })

  if (isDev) {
    win.loadURL(DEV_SERVER_URL)
    win.webContents.openDevTools()
  } else {
    win.loadFile(path.join(__dirname, '..', '..', 'frontend', 'dist', 'index.html'))
  }

  win.on('closed', () => {
    mainWindow = null
  })
  return win
}

function signalBackendReady(port: number): void {
  backendPort = port
  mainWindow?.webContents.send('backend-ready', port)
}

function signalBackendError(message: string): void {
  backendError = message
  mainWindow?.webContents.send('backend-error', message)
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

async function launchApp(
  appDataDir: string,
  imageLibraryDir: string,
  convertToWebp: boolean,
): Promise<void> {
  currentAppDataDir = appDataDir
  currentImageLibraryDir = imageLibraryDir
  currentConvertToWebp = convertToWebp
  backendPort = null
  backendError = null
  mainWindow = createMainWindow()

  if (isDev) {
    // Dev: the developer runs the backend on port 8000; DesktopGate polls /health.
    signalBackendReady(DEV_BACKEND_PORT)
    return
  }

  // A config-loaded start can point at a drive that is no longer mounted.
  const dirError = prepareStorageDirs(appDataDir, imageLibraryDir)
  if (dirError) {
    signalBackendError(dirError)
    return
  }

  let port: number
  try {
    port = await findFreePort()
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
    convertToWebp,
    onReady: (readyPort) => {
      ready = true
      console.log(`[electron] Backend ready on port ${readyPort}`)
      signalBackendReady(readyPort)
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
    const timer = setTimeout(resolve, timeoutMs)
    child.once('exit', () => {
      clearTimeout(timer)
      resolve()
    })
    child.kill('SIGTERM')
  })
}

// Lifecycle

function start(): void {
  const config = loadConfig()
  if (config) {
    void launchApp(config.appDataDir, config.imageLibraryDir, config.convertToWebp)
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
  if (hasInstanceLock) start()
})

app.on('window-all-closed', () => {
  void stopSidecar()
  if (process.platform !== 'darwin') app.quit()
})

app.on('activate', () => {
  if (hasInstanceLock && BrowserWindow.getAllWindows().length === 0) start()
})

app.on('will-quit', () => {
  void stopSidecar()
})
