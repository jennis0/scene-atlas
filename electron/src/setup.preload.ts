import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('setupAPI', {
  getDefaultDirs: (): Promise<{ appDataDir: string; imageLibraryDir: string }> =>
    ipcRenderer.invoke('setup:get-default-dirs'),

  chooseDirectory: (): Promise<string | null> =>
    ipcRenderer.invoke('setup:choose-directory'),

  complete: (appDataDir: string, imageLibraryDir: string, convertToWebp: boolean): void =>
    ipcRenderer.send('setup:complete', appDataDir, imageLibraryDir, convertToWebp),
})
