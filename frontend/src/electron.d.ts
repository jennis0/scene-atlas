/**
 * Global type augmentation for the electronAPI injected by the Electron
 * preload script.  Only present when the app is running inside Electron.
 */

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

  // Storage path IPC
  getAppDataDir(): Promise<string | null>
  getImageLibraryDir(): Promise<string | null>
  chooseAppDataDir(): Promise<string | null>
  chooseImageLibraryDir(): Promise<string | null>
  /**
   * Saves config and restarts the app. Call only when user confirms file-move intent.
   * Resolves (with an error) only if the new locations can't be used.
   */
  changeStorageDirs(appDataDir: string, imageLibraryDir: string): Promise<{ error: string | null }>

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
