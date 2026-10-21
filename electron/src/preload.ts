import { contextBridge, ipcRenderer, webFrame, webUtils } from 'electron'
// Types only: a sandboxed preload can't load local modules.
import type { DefaultDirs, FolderKind, LibraryDirs } from './libraryDirs'

// What the loading page can offer after a startup failure (design/library-setup.md §3.3).
interface StartupActions {
  retry: boolean
  chooseFolders: boolean
}
type ErrorListener = (message: string, actions: StartupActions) => void
const NO_ACTIONS: StartupActions = { retry: false, chooseFolders: false }

// Remember the last error so a subscriber that registers after it arrived still
// receives it. The main process re-sends it on every page load.
let backendError: string | null = null
let backendErrorActions: StartupActions = NO_ACTIONS
const errorListeners = new Set<ErrorListener>()

ipcRenderer.on('backend-error', (_event, message: string, actions?: StartupActions) => {
  backendError = message
  backendErrorActions = { ...NO_ACTIONS, ...actions }
  errorListeners.forEach((cb) => cb(message, backendErrorActions))
})

// Read from the app config before the page's first paint (a snapshot):
// - the UI's display choices (design/first-run.md); the UI keeps later changes itself;
// - whether setup's library step is done (design/library-setup.md §2.2).
let displayPrefs: Record<string, string> = {}
let libraryChosen = false
try {
  const state = ipcRenderer.sendSync('prefs:get-sync')
  displayPrefs = state?.displayPrefs ?? {}
  libraryChosen = state?.libraryChosen === true
} catch {
  // Main process unavailable: the UI falls back to its localStorage
}

// Zoom (frontend/src/lib/zoom.ts): a percentage display choice, applied here so the page
// paints at it from the start. A sandboxed preload can't import shared modules, hence the
// key (ZOOM_STORAGE_KEY there) and range here.
function zoomFactor(percent: unknown): number | null {
  const value = Number(percent)
  return Number.isFinite(value) && value >= 50 && value <= 300 ? value / 100 : null
}
const savedZoom = zoomFactor(displayPrefs['scene-atlas-zoom'])
if (savedZoom !== null) webFrame.setZoomFactor(savedZoom)

contextBridge.exposeInMainWorld('electronAPI', {
  platform: process.platform,

  displayPrefs,
  setDisplayPref: (key: string, value: string): Promise<void> =>
    ipcRenderer.invoke('prefs:set', key, value),
  setWindowColors: (colors: { background: string; foreground: string }): Promise<void> =>
    ipcRenderer.invoke('window:set-colors', colors),

  onBackendError: (callback: ErrorListener): (() => void) => {
    errorListeners.add(callback)
    if (backendError !== null) callback(backendError, backendErrorActions)
    return () => {
      errorListeners.delete(callback)
    }
  },
  // The loading page's actions: start the backend again on the same folders, or go back to
  // the default folders and the setup wizard's library step. Both replace the page.
  retryStartup: (): Promise<void> => ipcRenderer.invoke('startup:retry'),
  chooseFoldersAgain: (): Promise<void> => ipcRenderer.invoke('startup:choose-folders'),

  // The library's folders (design/library-setup.md)
  libraryChosen,
  getStorageDirs: (): Promise<LibraryDirs & { defaults: DefaultDirs }> =>
    ipcRenderer.invoke('library:get-dirs'),
  chooseFolder: (kind: FolderKind, current?: string): Promise<string | null> =>
    ipcRenderer.invoke('library:choose-folder', kind, current),
  // Resolves only when the folders are rejected or unchanged; otherwise the backend
  // restarts on them and this page is replaced.
  applyLibrary: (dirs: LibraryDirs): Promise<{ error: string | null; restarted: boolean }> =>
    ipcRenderer.invoke('library:apply', dirs),

  // Local imports (design/local-ingest.md): the backend reads these paths itself.
  // '' for a File with no path on disk.
  getPathForFile: (file: File): string => webUtils.getPathForFile(file),
  chooseImportFolders: (): Promise<string[]> => ipcRenderer.invoke('imports:choose-folders'),
  chooseImportFiles: (): Promise<string[]> => ipcRenderer.invoke('imports:choose-files'),

  setZoom: (percent: number): void => {
    const factor = zoomFactor(percent)
    if (factor !== null) webFrame.setZoomFactor(factor)
  },

  // Updates (design/electron.md#updates). The state is null before the updater exists.
  getUpdateState: (): Promise<unknown> => ipcRenderer.invoke('updates:get-state'),
  checkForUpdates: (): Promise<unknown> => ipcRenderer.invoke('updates:check'),
  setUpdateChoice: (choice: string): Promise<unknown> =>
    ipcRenderer.invoke('updates:set-choice', choice),
  downloadUpdate: (): Promise<unknown> => ipcRenderer.invoke('updates:download'),
  // Quits into the installer; resolves only if there was nothing to install.
  installUpdate: (): Promise<void> => ipcRenderer.invoke('updates:install'),
  openUpdateDownload: (): Promise<void> => ipcRenderer.invoke('updates:open-download'),
  onUpdateState: (callback: (state: unknown) => void): (() => void) => {
    const listener = (_event: Electron.IpcRendererEvent, state: unknown) => {
      callback(state)
    }
    ipcRenderer.on('updates:state', listener)
    return () => {
      ipcRenderer.removeListener('updates:state', listener)
    }
  },
})
