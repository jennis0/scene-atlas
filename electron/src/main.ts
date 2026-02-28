import { app, BrowserWindow, dialog, ipcMain, shell } from 'electron'
import * as fs from 'fs'
import * as path from 'path'
import { ChildProcess } from 'child_process'
import { findFreePort, spawnSidecar } from './sidecar'
import { getDefaultDataDir, loadConfig, saveConfig } from './config'

let mainWindow: BrowserWindow | null = null
let setupWindow: BrowserWindow | null = null
let sidecarProcess: ChildProcess | null = null
let currentDataDir: string | null = null

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
        height: 40,
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

// ── IPC handlers for the setup window ──────────────────────────────────────

ipcMain.handle('setup:get-default-dir', () => getDefaultDataDir())

ipcMain.handle('setup:choose-directory', async () => {
  const result = await dialog.showOpenDialog(setupWindow!, {
    title: 'Choose Library Location',
    defaultPath: getDefaultDataDir(),
    properties: ['openDirectory', 'createDirectory'],
    buttonLabel: 'Select Folder',
  })
  return result.canceled ? null : result.filePaths[0]
})

ipcMain.on('setup:complete', (_event, dataDir: string) => {
  fs.mkdirSync(dataDir, { recursive: true })
  saveConfig({ dataDir })
  setupWindow?.close()
  setupWindow = null
  launchApp(dataDir)
})

// ── IPC handlers for the system settings panel ──────────────────────────────

ipcMain.handle('system:get-data-dir', () => currentDataDir)

ipcMain.handle('system:open-data-dir', async () => {
  if (!currentDataDir) return
  await shell.openPath(currentDataDir)
})

ipcMain.handle('system:choose-data-dir', async () => {
  const result = await dialog.showOpenDialog(mainWindow!, {
    title: 'Choose Library Location',
    defaultPath: currentDataDir ?? getDefaultDataDir(),
    properties: ['openDirectory', 'createDirectory'],
    buttonLabel: 'Select Folder',
  })
  return result.canceled ? null : result.filePaths[0]
})

ipcMain.handle('system:change-data-dir', (_event, newDataDir: string) => {
  fs.mkdirSync(newDataDir, { recursive: true })
  saveConfig({ dataDir: newDataDir })
  // Relaunch with the new data directory
  app.relaunch()
  app.exit(0)
})

// ── IPC handlers for renderer file system access ─────────────────────────────

/**
 * Recursively walk a directory and return all file paths.
 * relativePath is relative to the parent of dirPath (so the folder name is
 * included), using forward slashes for consistency with webkitRelativePath.
 */
function walkDir(
  dirPath: string,
  relativeTo: string,
  results: Array<{ relativePath: string; absolutePath: string }>,
): void {
  let entries: fs.Dirent[]
  try {
    entries = fs.readdirSync(dirPath, { withFileTypes: true })
  } catch {
    return
  }
  for (const entry of entries) {
    const absPath = path.join(dirPath, entry.name)
    const relPath = path.relative(relativeTo, absPath).replace(/\\/g, '/')
    if (entry.isDirectory()) {
      walkDir(absPath, relativeTo, results)
    } else if (entry.isFile()) {
      results.push({ relativePath: relPath, absolutePath: absPath })
    }
  }
}

/**
 * Returns all files under a directory with relativePath starting from the
 * directory name itself (matching webkitRelativePath convention).
 */
ipcMain.handle('fs:read-directory', (_event, dirPath: string) => {
  const parentDir = path.dirname(dirPath)
  const results: Array<{ relativePath: string; absolutePath: string }> = []
  walkDir(dirPath, parentDir, results)
  return results
})

/**
 * Read a file and return its bytes. Used by the renderer to create File
 * objects from paths returned by fs:read-directory.
 */
ipcMain.handle('fs:read-file-bytes', (_event, absolutePath: string) => {
  const data = fs.readFileSync(absolutePath)
  return { data: new Uint8Array(data.buffer, data.byteOffset, data.byteLength) }
})

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

async function launchApp(dataDir: string): Promise<void> {
  currentDataDir = dataDir
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

  fs.mkdirSync(dataDir, { recursive: true })

  // Log file for sidecar output — helps diagnose startup crashes
  const logPath = path.join(app.getPath('userData'), 'backend.log')
  const logStream = fs.createWriteStream(logPath, { flags: 'a' })
  logStream.write(`\n--- Scene Atlas started ${new Date().toISOString()} ---\n`)
  logStream.write(`port=${port} data=${dataDir}\n`)
  console.log(`[electron] Spawning backend on port ${port}, data=${dataDir}`)
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
    dataDir,
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
    launchApp(config.dataDir)
  } else {
    showSetupWindow()
  }
})

app.on('window-all-closed', () => {
  killSidecar()
  if (process.platform !== 'darwin') app.quit()
})

app.on('activate', () => {
  if (mainWindow === null && setupWindow === null) {
    const config = loadConfig()
    if (config) launchApp(config.dataDir)
    else showSetupWindow()
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
