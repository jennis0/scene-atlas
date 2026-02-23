import { app, BrowserWindow, dialog, ipcMain, shell } from 'electron'
import * as fs from 'fs'
import * as path from 'path'
import { ChildProcess } from 'child_process'
import { findFreePort, spawnSidecar } from './sidecar'
import { getDefaultDataDir, loadConfig, saveConfig } from './config'

let mainWindow: BrowserWindow | null = null
let setupWindow: BrowserWindow | null = null
let sidecarProcess: ChildProcess | null = null

const isDev = !app.isPackaged

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

// ── Setup window ────────────────────────────────────────────────────────────

function showSetupWindow(): void {
  setupWindow = new BrowserWindow({
    width: 600,
    height: 640,
    resizable: true,
    minWidth: 520,
    minHeight: 560,
    backgroundColor: '#0e1118',
    titleBarStyle: process.platform === 'darwin' ? 'hiddenInset' : 'default',
    webPreferences: {
      preload: path.join(__dirname, 'setup.preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  })

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
    titleBarStyle: process.platform === 'darwin' ? 'hiddenInset' : 'default',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  })

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
  console.log(`[electron] Spawning backend on port ${port}, data=${dataDir}`)

  const child = spawnSidecar(
    port,
    dataDir,
    (readyPort) => {
      console.log(`[electron] Backend ready on port ${readyPort}`)
      mainWindow?.webContents.send('backend-ready', readyPort)
    },
    (line) => console.log(line),
  )

  sidecarProcess = child

  // If the sidecar process exits before signalling ready, report the error
  child.on('exit', (code) => {
    if (code !== 0 && code !== null) {
      mainWindow?.webContents.send(
        'backend-error',
        `Backend process exited unexpectedly (code ${code}). Check that the sidecar binary is present.`,
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
