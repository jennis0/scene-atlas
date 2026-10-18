import { contextBridge, ipcRenderer, webUtils } from 'electron'

// Remember the last error so a subscriber that registers after it arrived still
// receives it. The main process re-sends it on every page load.
let backendError: string | null = null
const errorListeners = new Set<(message: string) => void>()

ipcRenderer.on('backend-error', (_event, message: string) => {
  backendError = message
  errorListeners.forEach((cb) => cb(message))
})

// The UI's display choices from the app config, read before the page's first paint
// (design/first-run.md). A snapshot: the UI keeps later changes itself.
let displayPrefs: Record<string, string> = {}
try {
  displayPrefs = ipcRenderer.sendSync('prefs:get-sync') ?? {}
} catch {
  // Main process unavailable: the UI falls back to its localStorage
}

contextBridge.exposeInMainWorld('electronAPI', {
  platform: process.platform,

  displayPrefs,
  setDisplayPref: (key: string, value: string): Promise<void> =>
    ipcRenderer.invoke('prefs:set', key, value),
  setWindowColors: (colors: { background: string; foreground: string }): Promise<void> =>
    ipcRenderer.invoke('window:set-colors', colors),

  onBackendError: (callback: (message: string) => void): (() => void) => {
    errorListeners.add(callback)
    if (backendError !== null) callback(backendError)
    return () => {
      errorListeners.delete(callback)
    }
  },

  getAppDataDir: (): Promise<string | null> => ipcRenderer.invoke('system:get-app-data-dir'),
  getImageLibraryDir: (): Promise<string | null> =>
    ipcRenderer.invoke('system:get-image-library-dir'),
  chooseAppDataDir: (): Promise<string | null> => ipcRenderer.invoke('system:choose-app-data-dir'),
  chooseImageLibraryDir: (): Promise<string | null> =>
    ipcRenderer.invoke('system:choose-image-library-dir'),
  // Saves config AND restarts. Call only when user confirms they've moved files.
  // Resolves only if the new locations are rejected.
  changeStorageDirs: (
    appDataDir: string,
    imageLibraryDir: string,
  ): Promise<{ error: string | null }> =>
    ipcRenderer.invoke('system:change-storage-dirs', appDataDir, imageLibraryDir),

  // Local imports (design/local-ingest.md): the backend reads these paths itself.
  // '' for a File with no path on disk.
  getPathForFile: (file: File): string => webUtils.getPathForFile(file),
  chooseImportFolders: (): Promise<string[]> => ipcRenderer.invoke('imports:choose-folders'),
  chooseImportFiles: (): Promise<string[]> => ipcRenderer.invoke('imports:choose-files'),
})
