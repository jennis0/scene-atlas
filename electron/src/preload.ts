import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('electronAPI', {
  onBackendReady: (callback: (port: number) => void) => {
    ipcRenderer.on('backend-ready', (_event, port: number) => callback(port))
  },
  onBackendError: (callback: (message: string) => void) => {
    ipcRenderer.on('backend-error', (_event, message: string) => callback(message))
  },
})
