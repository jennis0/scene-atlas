import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('electronAPI', {
  platform: process.platform,

  onBackendReady: (callback: (port: number) => void) => {
    ipcRenderer.once('backend-ready', (_event, port: number) => callback(port))
  },
  onBackendError: (callback: (message: string) => void) => {
    ipcRenderer.once('backend-error', (_event, message: string) => callback(message))
  },

  // Storage path IPC
  getAppDataDir: (): Promise<string | null> => ipcRenderer.invoke('system:get-app-data-dir'),
  getImageLibraryDir: (): Promise<string | null> => ipcRenderer.invoke('system:get-image-library-dir'),
  chooseAppDataDir: (): Promise<string | null> => ipcRenderer.invoke('system:choose-app-data-dir'),
  chooseImageLibraryDir: (): Promise<string | null> => ipcRenderer.invoke('system:choose-image-library-dir'),
  // Saves config AND restarts. Call only when user confirms they've moved files.
  changeStorageDirs: (appDataDir: string, imageLibraryDir: string): Promise<void> =>
    ipcRenderer.invoke('system:change-storage-dirs', appDataDir, imageLibraryDir),

})
