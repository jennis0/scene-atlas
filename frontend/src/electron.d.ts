/**
 * Global type augmentation for the electronAPI injected by the Electron
 * preload script.  Only present when the app is running inside Electron.
 */

interface ElectronAPI {
  readonly platform: 'darwin' | 'win32' | 'linux'

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
}

declare global {
  interface Window {
    electronAPI?: ElectronAPI
  }
}

export {}
