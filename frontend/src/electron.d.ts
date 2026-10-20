/**
 * Global type augmentation for the electronAPI injected by the Electron
 * preload script.  Only present when the app is running inside Electron.
 */

/** A library's folders (design/library-setup.md §1) */
export type LibraryFolderKind = 'appData' | 'store' | 'linked'

export interface LibraryDirs {
  /** App data: database, search index, thumbnails ("Search data") */
  appData: string
  /** Imported originals and backups ("Imported images") */
  store: string
  /** The user's own maps folder, read where it is; null when none is linked */
  linked: string | null
}

export interface StorageDirs extends LibraryDirs {
  /** The defaults a new library starts on (the provisional first-launch folders) */
  defaults: { appData: string; store: string }
}

export interface ApplyLibraryResult {
  error: string | null
  restarted: boolean
}

export interface ElectronAPI {
  readonly platform: 'darwin' | 'win32' | 'linux'

  // Display choices (design/first-run.md): localStorage is tied to the backend's port, so
  // the desktop app also keeps them in its config.
  /** The saved choices, read before the page loaded (a snapshot) */
  readonly displayPrefs: Readonly<Record<string, string>>
  setDisplayPref(key: string, value: string): Promise<void>
  /** Match the window background and the Windows/Linux title bar to these hex colours */
  setWindowColors(colors: { background: string; foreground: string }): Promise<void>

  /** Subscribe to fatal backend errors (fires immediately if one already arrived). Used by loading.html. */
  onBackendError(
    callback: (message: string, actions: { retry: boolean; chooseFolders: boolean }) => void,
  ): () => void
  /** Loading page: start the backend again on the same folders. */
  retryStartup(): Promise<void>
  /** Loading page: back to the default folders and the setup wizard's library step. */
  chooseFoldersAgain(): Promise<void>

  // The library's folders (design/library-setup.md)
  /** The setup wizard's library step is done, so it resumes after it (read before the page loaded) */
  readonly libraryChosen: boolean
  /** The folders the backend runs on, and the defaults */
  getStorageDirs(): Promise<StorageDirs>
  /** A plain native folder picker, starting at *current*; null when cancelled. Check the
   * choice with POST /library/inspect. */
  chooseFolder(kind: LibraryFolderKind, current?: string): Promise<string | null>
  /**
   * Validates and prepares the folders, then saves them with libraryChosen.
   * Resolves `{ error }` when they are rejected, and `{ error: null, restarted: false }`
   * when nothing changed (or in dev, where the developer's backend ignores them).
   * Otherwise it never resolves: the backend stops, replaced first-launch folders are
   * deleted, and the backend restarts in this window (loading page, then the UI reloads).
   */
  applyLibrary(dirs: LibraryDirs): Promise<ApplyLibraryResult>

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
