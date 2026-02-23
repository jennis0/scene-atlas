/**
 * Global type augmentation for the electronAPI injected by the Electron
 * preload script.  Only present when the app is running inside Electron.
 */

interface ElectronAPI {
  // Backend lifecycle events
  onBackendReady(callback: (port: number) => void): void
  onBackendError(callback: (message: string) => void): void

  // System settings IPC
  getDataDir(): Promise<string | null>
  openDataDir(): Promise<void>
  chooseDataDir(): Promise<string | null>
  changeDataDir(newPath: string): Promise<void>

  // Filesystem access for drag-and-drop folder traversal
  readDirectory(dirPath: string): Promise<Array<{ relativePath: string; absolutePath: string }>>
  readFileBytes(absolutePath: string): Promise<{ data: Uint8Array }>
}

declare global {
  interface Window {
    electronAPI?: ElectronAPI
    /** Port injected by DesktopGate after the backend signals ready. */
    __SCENE_ATLAS_PORT__?: number
  }
}

export {}
