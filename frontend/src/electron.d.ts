/**
 * Global type augmentation for the electronAPI injected by the Electron
 * preload script.  Only present when the app is running inside Electron.
 */

interface ElectronAPI {
  readonly platform: 'darwin' | 'win32' | 'linux'

  /**
   * Subscribe to the backend port. Fires immediately if the signal already
   * arrived, and may fire again with the same port. Returns an unsubscribe function.
   */
  onBackendReady(callback: (port: number) => void): () => void
  /** Subscribe to fatal backend errors; same delivery rules as onBackendReady. */
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
    /** Port injected by DesktopGate after the backend signals ready. */
    __SCENE_ATLAS_PORT__?: number
  }
}

export {}
