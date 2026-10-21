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

/** How the desktop app updates itself: download and install on restart, say a version is
 * out and wait for the user, or no checks of its own (electron/src/updatePolicy.ts) */
export type UpdateChoice = 'automatic' | 'ask' | 'off'

/** The desktop app's updater (electron/src/updatePolicy.ts, design/electron.md#updates) */
export interface AppUpdateState {
  status:
    | 'unsupported'
    | 'idle'
    | 'checking'
    | 'up-to-date'
    | 'available'
    | 'downloading'
    | 'ready'
    | 'error'
  /** 'install' downloads and installs; 'notify' links to the download (macOS, .deb) */
  mode: 'install' | 'notify'
  currentVersion: string
  /** The user's choice, or the default ('ask') until they make one */
  choice: UpdateChoice
  /** False until a choice is made; the app makes no checks of its own until then */
  choiceMade: boolean
  version?: string
  percent?: number
  error?: string
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
  /** Restart the backend on the same folders, for settings that apply only then. Resolves
   * false when it can't (dev, where the developer runs the backend); otherwise it never
   * resolves: the loading page, then the UI reloads. */
  restartBackend(): Promise<boolean>

  // Local imports (design/local-ingest.md)
  /** The file's path on disk, or '' if it has none. */
  getPathForFile(file: File): string
  /** Native pickers; resolve to [] when cancelled. */
  chooseImportFolders(): Promise<string[]>
  chooseImportFiles(): Promise<string[]>

  // Zoom (lib/zoom.ts)
  /** Zoom the page to this percentage (50–300) */
  setZoom(percent: number): void

  // Updates. The state is null until the updater has started.
  getUpdateState(): Promise<AppUpdateState | null>
  /** Check now, even when automatic checks are off */
  checkForUpdates(): Promise<AppUpdateState | null>
  setUpdateChoice(choice: UpdateChoice): Promise<AppUpdateState | null>
  /** Download the version found (install mode, when the choice isn't automatic) */
  downloadUpdate(): Promise<AppUpdateState | null>
  /** Quit into the downloaded version's installer */
  installUpdate(): Promise<void>
  /** Open the new version's release page (notify mode) */
  openUpdateDownload(): Promise<void>
  onUpdateState(callback: (state: AppUpdateState) => void): () => void
}

declare global {
  interface Window {
    electronAPI?: ElectronAPI
  }
}
