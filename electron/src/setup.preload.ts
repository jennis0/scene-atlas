import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('setupAPI', {
  getDefaultDirs: (): Promise<{ appDataDir: string; imageLibraryDir: string }> =>
    ipcRenderer.invoke('setup:get-default-dirs'),

  chooseDirectory: (
    kind: 'appData' | 'imageLibrary',
    currentDir: string,
    otherRoot: string,
  ): Promise<string | null> =>
    ipcRenderer.invoke('setup:choose-directory', kind, currentDir, otherRoot),

  complete: (appDataDir: string, imageLibraryDir: string): Promise<{ error: string | null }> =>
    ipcRenderer.invoke('setup:complete', appDataDir, imageLibraryDir),
})
