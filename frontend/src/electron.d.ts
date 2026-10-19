/**
 * Global type augmentation for the electronAPI injected by the Electron
 * preload script.  Only present when the app is running inside Electron.
 */

interface StorageDirs {
  appData: string
  store: string
  linked: string | null
  /** The provisional defaults (getDefaultDirs) */
  defaults: { appData: string; store: string }
}

interface ElectronAPI {
  readonly platform: 'darwin' | 'win32' | 'linux'

  // Display choices (design/first-run.md): localStorage is tied to the backend's port, so
  // the desktop app also keeps them in its config.
  /** The saved choices, read before the page loaded (a snapshot) */
  readonly displayPrefs: Readonly<Record<string, string>>
  setDisplayPref(key: string, value: string): Promise<void>
  /** Match the window background and the Windows/Linux title bar to these hex colours */
  setWindowColors(colors: { background: string; foreground: string }): Promise<void>

  /** Subscribe to fatal backend errors (fires immediately if one already arrived). Used by loading.html. */
  onBackendError(callback: (message: string) => void): () => void

  // Library folders (design/library-setup.md "Interfaces between the parts")
  /** The wizard's library step is done (config `libraryChosen`), read with displayPrefs */
  readonly libraryChosen: boolean
  getStorageDirs(): Promise<StorageDirs>
  /** A plain folder picker, no warning box: the wizard checks the folder with inspect */
  chooseFolder(kind: 'appData' | 'store' | 'linked', current?: string): Promise<string | null>
  /**
   * Validates and prepares the folders, then saves the config with libraryChosen: true.
   * Nothing changed: resolves { error: null, restarted: false }. Something changed: stops
   * the backend, deletes replaced provisional folders and restarts the backend in this
   * window (loading page, then the UI reloads); it never resolves in that case.
   */
  applyLibrary(dirs: {
    appData: string
    store: string
    linked: string | null
  }): Promise<{ error: string | null; restarted: boolean }>

  // Local imports (design/local-ingest.md)
  /** The file's path on disk, or '' if it has none. */
  getPathForFile(file: File): string
  /** Native pickers; resolve to [] when cancelled. */
  chooseImportFolders(): Promise<string[]>
  chooseImportFiles(): Promise<string[]>
}

declare global {
  interface Window {
    electronAPI?: ElectronAPI
  }
}

export {}
