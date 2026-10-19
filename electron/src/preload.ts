import { contextBridge, ipcRenderer, webUtils } from 'electron'

// Remember the last error so a subscriber that registers after it arrived still
// receives it. The main process re-sends it on every page load.
let backendError: string | null = null
const errorListeners = new Set<(message: string) => void>()

ipcRenderer.on('backend-error', (_event, message: string) => {
  backendError = message
  errorListeners.forEach((cb) => cb(message))
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

type FolderKind = 'appData' | 'store' | 'linked'
interface LibraryDirs {
  appData: string
  store: string
  linked: string | null
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

  // The library's folders (design/library-setup.md)
  libraryChosen,
  getStorageDirs: (): Promise<LibraryDirs & { defaults: { appData: string; store: string } }> =>
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
})
