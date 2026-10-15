import { app, BrowserWindow, dialog, ipcMain, shell } from 'electron'
import * as fs from 'fs'
import * as path from 'path'
import { ChildProcess } from 'child_process'
import { findFreePort, spawnSidecar } from './sidecar'
import { getDefaultDirs, loadConfig, saveConfig } from './config'

let mainWindow: BrowserWindow | null = null
let setupWindow: BrowserWindow | null = null
let sidecarProcess: ChildProcess | null = null
let currentAppDataDir: string | null = null
let currentImageLibraryDir: string | null = null
let currentConvertToWebp: boolean = true

const isDev = !app.isPackaged
const isMac = process.platform === 'darwin'

// ── Shared window helpers ────────────────────────────────────────────────────

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

/** Enable F12 / Ctrl+Shift+I to toggle dev tools in any build. */
function enableDevToolsShortcut(win: BrowserWindow): void {
  win.webContents.on('before-input-event', (_event, input) => {
    if (
      input.key === 'F12' ||
      (input.control && input.shift && input.key === 'I')
    ) {
      win.webContents.toggleDevTools()
    }
  })
}

// ── Setup window IPC ────────────────────────────────────────────────────────

ipcMain.handle('setup:get-default-dirs', () => getDefaultDirs())

ipcMain.handle('setup:choose-directory', async () => {
  const result = await dialog.showOpenDialog(setupWindow!, {
    title: 'Choose Folder',
    properties: ['openDirectory', 'createDirectory'],
    buttonLabel: 'Select Folder',
  })
  return result.canceled ? null : result.filePaths[0]
})

ipcMain.handle('setup:complete', async (_event, appDataDir: string, imageLibraryDir: string, convertToWebp: boolean) => {
  // Create both roots before launching the backend (backend validates they exist)
  fs.mkdirSync(appDataDir, { recursive: true })
  fs.mkdirSync(imageLibraryDir, { recursive: true })

  // Writability check: write and delete a temp file in each directory
  for (const dir of [appDataDir, imageLibraryDir]) {
    const testFile = path.join(dir, `.write-test-${Date.now()}`)
    try {
      fs.writeFileSync(testFile, 'test')
      fs.unlinkSync(testFile)
    } catch (err) {
      const label = dir === appDataDir ? 'App data directory' : 'Image library directory'
      return { error: `${label} is not writable: ${dir}\n${(err as Error).message}` }
    }
  }

  saveConfig({ appDataDir, imageLibraryDir, convertToWebp })
  setupWindow?.close()
  setupWindow = null
  launchApp(appDataDir, imageLibraryDir, convertToWebp)
  return { error: null }
})

// ── System settings IPC ─────────────────────────────────────────────────────

ipcMain.handle('system:get-app-data-dir', () => currentAppDataDir)
ipcMain.handle('system:get-image-library-dir', () => currentImageLibraryDir)

ipcMain.handle('system:choose-app-data-dir', async () => {
  const result = await dialog.showOpenDialog(mainWindow!, {
    title: 'Choose App Data Location',
    defaultPath: currentAppDataDir ?? getDefaultDirs().appDataDir,
    properties: ['openDirectory', 'createDirectory'],
    buttonLabel: 'Select Folder',
  })
  return result.canceled ? null : result.filePaths[0]
})

ipcMain.handle('system:choose-image-library-dir', async () => {
  const result = await dialog.showOpenDialog(mainWindow!, {
    title: 'Choose Image Library Location',
    defaultPath: currentImageLibraryDir ?? getDefaultDirs().imageLibraryDir,
    properties: ['openDirectory', 'createDirectory'],
    buttonLabel: 'Select Folder',
  })
  return result.canceled ? null : result.filePaths[0]
})

// Saves new paths to config and restarts.
// Called only when user explicitly clicks "Restart Now" in the Settings UI.
ipcMain.handle(
  'system:change-storage-dirs',
  (_event, newAppDataDir: string, newImageLibraryDir: string) => {
    saveConfig({
      appDataDir: newAppDataDir,
      imageLibraryDir: newImageLibraryDir,
      convertToWebp: currentConvertToWebp,
    })
    app.relaunch()
    app.exit(0)
  },
)

// ── IPC handlers for renderer file system access ─────────────────────────────

// ── Setup window ────────────────────────────────────────────────────────────

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
      sandbox: false,
    },
  })

  enableDevToolsShortcut(setupWindow)
  setupWindow.loadFile(path.join(__dirname, '..', 'setup.html'))

  setupWindow.on('closed', () => {
    setupWindow = null
    if (!mainWindow) app.quit()
  })
}

// ── Main app window ─────────────────────────────────────────────────────────

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

  enableDevToolsShortcut(win)

  if (isDev) {
    win.loadURL('http://localhost:5173')
    win.webContents.openDevTools()
  } else {
    win.loadFile(path.join(__dirname, '..', '..', 'frontend', 'dist', 'index.html'))
  }

  win.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url)
    return { action: 'deny' }
  })

  win.on('closed', () => { mainWindow = null })
  return win
}

// ── App launch (after setup is done or skipped) ─────────────────────────────

async function launchApp(appDataDir: string, imageLibraryDir: string, convertToWebp: boolean): Promise<void> {
  currentAppDataDir = appDataDir
  currentImageLibraryDir = imageLibraryDir
  currentConvertToWebp = convertToWebp
  mainWindow = createMainWindow()

  if (isDev) {
    // Dev: backend runs manually on port 8000.
    // Send backend-ready so DesktopGate unblocks and polls /health.
    mainWindow.webContents.on('did-finish-load', () => {
      mainWindow?.webContents.send('backend-ready', 8000)
    })
    return
  }

  let port: number
  try {
    port = await findFreePort()
  } catch (err) {
    console.error('Failed to find a free port:', err)
    mainWindow.webContents.on('did-finish-load', () => {
      mainWindow?.webContents.send('backend-error', 'Could not find a free port')
    })
    return
  }

  fs.mkdirSync(appDataDir, { recursive: true })
  fs.mkdirSync(imageLibraryDir, { recursive: true })

  // Log file for sidecar output — helps diagnose startup crashes
  const logPath = path.join(app.getPath('userData'), 'backend.log')
  const logStream = fs.createWriteStream(logPath, { flags: 'a' })
  logStream.write(`\n--- Scene Atlas started ${new Date().toISOString()} ---\n`)
  logStream.write(`port=${port} appData=${appDataDir} imageLibrary=${imageLibraryDir}\n`)
  console.log(`[electron] Spawning backend on port ${port}, appData=${appDataDir}, imageLibrary=${imageLibraryDir}`)
  console.log(`[electron] Sidecar log: ${logPath}`)

  // Collect recent output lines so we can show them in the error dialog
  const recentLines: string[] = []
  const logLine = (line: string) => {
    console.log(line)
    logStream.write(line + '\n')
    recentLines.push(line)
    if (recentLines.length > 50) recentLines.shift()
  }

  const child = spawnSidecar(
    port,
    appDataDir,
    imageLibraryDir,
    convertToWebp,
    (readyPort) => {
      console.log(`[electron] Backend ready on port ${readyPort}`)
      mainWindow?.webContents.send('backend-ready', readyPort)
    },
    logLine,
  )

  sidecarProcess = child

  // If the sidecar process exits before signalling ready, report the error
  child.on('exit', (code) => {
    logStream.write(`--- exited code=${code} ---\n`)
    logStream.end()
    if (code !== 0 && code !== null) {
      const tail = recentLines.slice(-10).join('\n')
      mainWindow?.webContents.send(
        'backend-error',
        `Backend crashed (exit code ${code}).\n\nLast output:\n${tail}\n\nFull log: ${logPath}`,
      )
    }
  })
}

// ── Electron lifecycle ───────────────────────────────────────────────────────

app.whenReady().then(() => {
  const config = loadConfig()
  if (config) {
    launchApp(config.appDataDir, config.imageLibraryDir, config.convertToWebp)
  } else {
    showSetupWindow()
  }
})

app.on('window-all-closed', () => {
  killSidecar()
  if (process.platform !== 'darwin') app.quit()
})

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    const config = loadConfig()
    if (config) {
      launchApp(config.appDataDir, config.imageLibraryDir, config.convertToWebp)
    } else {
      showSetupWindow()
    }
  }
})

app.on('will-quit', () => killSidecar())

function killSidecar(): void {
  if (sidecarProcess && !sidecarProcess.killed) {
    console.log('[electron] Killing backend sidecar')
    sidecarProcess.kill('SIGTERM')
    sidecarProcess = null
  }
}
