/**
 * Global type augmentation for the electronAPI injected by the Electron
 * preload script.  Only present when the app is running inside Electron.
 */

interface ElectronAPI {
  readonly platform: 'darwin' | 'win32' | 'linux'

  onBackendReady(callback: (port: number) => void): void
  onBackendError(callback: (message: string) => void): void

  // Storage path IPC
  getAppDataDir(): Promise<string | null>
  getImageLibraryDir(): Promise<string | null>
  chooseAppDataDir(): Promise<string | null>
  chooseImageLibraryDir(): Promise<string | null>
  /** Saves config and restarts the app. Call only when user confirms file-move intent. */
  changeStorageDirs(appDataDir: string, imageLibraryDir: string): Promise<void>
}

declare global {
  interface Window {
    electronAPI?: ElectronAPI
    /** Port injected by DesktopGate after the backend signals ready. */
    __SCENE_ATLAS_PORT__?: number
  }
}

export {}
