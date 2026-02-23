import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('electronAPI', {
  onBackendReady: (callback: (port: number) => void) => {
    ipcRenderer.once('backend-ready', (_event, port: number) => callback(port))
  },
  onBackendError: (callback: (message: string) => void) => {
    ipcRenderer.once('backend-error', (_event, message: string) => callback(message))
  },

  // System settings
  getDataDir: (): Promise<string | null> => ipcRenderer.invoke('system:get-data-dir'),
  openDataDir: (): Promise<void> => ipcRenderer.invoke('system:open-data-dir'),
  chooseDataDir: (): Promise<string | null> => ipcRenderer.invoke('system:choose-data-dir'),
  changeDataDir: (newPath: string): Promise<void> => ipcRenderer.invoke('system:change-data-dir', newPath),

  // Filesystem access for drag-and-drop folder traversal
  readDirectory: (
    dirPath: string,
  ): Promise<Array<{ relativePath: string; absolutePath: string }>> =>
    ipcRenderer.invoke('fs:read-directory', dirPath),
  readFileBytes: (absolutePath: string): Promise<{ data: Uint8Array }> =>
    ipcRenderer.invoke('fs:read-file-bytes', absolutePath),
})
