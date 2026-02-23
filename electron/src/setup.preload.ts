import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('setupAPI', {
  getDefaultDir: (): Promise<string> =>
    ipcRenderer.invoke('setup:get-default-dir'),

  chooseDirectory: (): Promise<string | null> =>
    ipcRenderer.invoke('setup:choose-directory'),

  complete: (dataDir: string): void =>
    ipcRenderer.send('setup:complete', dataDir),
})
