// Native folder and file pickers: the storage folders (setup and Settings) and local
// imports. main.ts registers the IPC that opens them.
import { app, BrowserWindow, dialog } from 'electron'
import { hasForeignEntries } from './storageDirs'

export type StorageKind = 'appData' | 'imageLibrary'

const IMPORT_EXTENSIONS = ['jpg', 'jpeg', 'png', 'webp', 'mp4', 'webm', 'zip']

async function pickDirectory(
  win: BrowserWindow | null,
  title: string,
  defaultPath?: string,
): Promise<string | null> {
  const options: Electron.OpenDialogOptions = {
    title,
    // Electron 43+ opens dialogs in Downloads unless given a starting folder.
    defaultPath: defaultPath ?? app.getPath('home'),
    properties: ['openDirectory', 'createDirectory'],
    buttonLabel: 'Select Folder',
  }
  const result = win
    ? await dialog.showOpenDialog(win, options)
    : await dialog.showOpenDialog(options)
  return result.canceled ? null : result.filePaths[0]
}

function storagePicker(kind: StorageKind): { title: string; foreignDetail: string } {
  switch (kind) {
    case 'appData':
      return {
        title: 'Choose App Data Folder',
        foreignDetail:
          'Scene Atlas keeps its database, thumbnails and search index here. ' +
          'A new or empty folder keeps them apart from your other files.',
      }
    case 'imageLibrary':
      return {
        title: 'Choose Image Library Folder',
        foreignDetail:
          'Scene Atlas keeps its own copy of every image you import here, in its own ' +
          'folder layout. It will not show the files already in this folder: bring ' +
          'your existing maps in with Import instead.\n\nA new or empty folder is best.',
      }
  }
}

/** Pick a storage folder, warning when it already holds files Scene Atlas didn't create
 * (most likely the user's existing collection, design/electron.md). Null when cancelled. */
export async function pickStorageDir(
  win: BrowserWindow | null,
  kind: StorageKind,
  defaultPath?: string,
  otherRoot?: string,
): Promise<string | null> {
  const { title, foreignDetail } = storagePicker(kind)
  for (;;) {
    const chosen = await pickDirectory(win, title, defaultPath)
    if (!chosen || !hasForeignEntries(chosen, otherRoot)) return chosen
    const options: Electron.MessageBoxOptions = {
      type: 'warning',
      title: 'Folder is not empty',
      message: 'This folder already has other files in it.',
      detail: foreignDetail,
      buttons: ['Choose Another Folder', 'Use This Folder'],
      defaultId: 0,
      cancelId: 0,
      noLink: true,
    }
    const { response } = win
      ? await dialog.showMessageBox(win, options)
      : await dialog.showMessageBox(options)
    if (response === 1) return chosen
    defaultPath = chosen
  }
}

/** Files and folders to import (design/local-ingest.md). Empty when cancelled. */
export async function pickImportPaths(
  win: BrowserWindow | null,
  kind: 'folders' | 'files',
): Promise<string[]> {
  const options: Electron.OpenDialogOptions =
    kind === 'folders'
      ? { title: 'Import folders', properties: ['openDirectory', 'multiSelections'] }
      : {
          title: 'Import files',
          properties: ['openFile', 'multiSelections'],
          filters: [{ name: 'Images, videos and zips', extensions: IMPORT_EXTENSIONS }],
        }
  options.buttonLabel = 'Import'
  const result = win
    ? await dialog.showOpenDialog(win, options)
    : await dialog.showOpenDialog(options)
  return result.canceled ? [] : result.filePaths
}
