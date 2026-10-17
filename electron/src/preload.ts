import { contextBridge, ipcRenderer } from 'electron'

// Remember the last backend signal so a subscriber that registers after it
// arrived (React mounts after the main process may already have sent it)
// still receives it. The main process re-sends on every page load.
let backendPort: number | null = null
let backendError: string | null = null
const readyListeners = new Set<(port: number) => void>()
const errorListeners = new Set<(message: string) => void>()

ipcRenderer.on('backend-ready', (_event, port: number) => {
  backendPort = port
  readyListeners.forEach((cb) => cb(port))
})
ipcRenderer.on('backend-error', (_event, message: string) => {
  backendError = message
  errorListeners.forEach((cb) => cb(message))
})

contextBridge.exposeInMainWorld('electronAPI', {
  platform: process.platform,

  onBackendReady: (callback: (port: number) => void): (() => void) => {
    readyListeners.add(callback)
    if (backendPort !== null) callback(backendPort)
    return () => {
      readyListeners.delete(callback)
    }
  },
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
})
