// Native folder and file pickers: the storage folders (setup and Settings) and local
// imports. main.ts registers the IPC that opens them; each picker opens over the window
// that asked, or on its own if that window has gone.
import { app, BrowserWindow, dialog } from 'electron'
import { hasForeignEntries } from './storageDirs'

export type StorageKind = 'appData' | 'imageLibrary'

const IMPORT_EXTENSIONS = ['jpg', 'jpeg', 'png', 'webp', 'mp4', 'webm', 'zip']

/** The chosen paths; empty when cancelled. */
async function openDialog(
  sender: Electron.WebContents,
  options: Electron.OpenDialogOptions,
): Promise<string[]> {
  const win = BrowserWindow.fromWebContents(sender)
  const result = win
    ? await dialog.showOpenDialog(win, options)
    : await dialog.showOpenDialog(options)
  return result.canceled ? [] : result.filePaths
}

/** Whether the user still wants a folder that already holds other files. */
async function confirmForeignFolder(
  sender: Electron.WebContents,
  detail: string,
): Promise<boolean> {
  const win = BrowserWindow.fromWebContents(sender)
  const options: Electron.MessageBoxOptions = {
    type: 'warning',
    title: 'Folder is not empty',
    message: 'This folder already has other files in it.',
    detail,
    buttons: ['Choose Another Folder', 'Use This Folder'],
    defaultId: 0,
    cancelId: 0,
    noLink: true,
  }
  const { response } = win
    ? await dialog.showMessageBox(win, options)
    : await dialog.showMessageBox(options)
  return response === 1
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
 * (most likely the user's existing collection, design/electron.md). Null when cancelled,
 * and when a dialog fails: the user can just try again. */
export async function pickStorageDir(
  sender: Electron.WebContents,
  kind: StorageKind,
  defaultPath?: string,
  otherRoot?: string,
): Promise<string | null> {
  const { title, foreignDetail } = storagePicker(kind)
  try {
    for (;;) {
      const [chosen] = await openDialog(sender, {
        title,
        // Electron 43+ opens dialogs in Downloads unless given a starting folder.
        defaultPath: defaultPath ?? app.getPath('home'),
        properties: ['openDirectory', 'createDirectory'],
        buttonLabel: 'Select Folder',
      })
      if (!chosen || !hasForeignEntries(chosen, otherRoot)) return chosen ?? null
      if (await confirmForeignFolder(sender, foreignDetail)) return chosen
      defaultPath = chosen
    }
  } catch (err) {
    console.error('[electron] Folder picker failed:', err)
    return null
  }
}

/** Files and folders to import (design/local-ingest.md). Empty when cancelled, and when
 * the dialog fails. */
export async function pickImportPaths(
  sender: Electron.WebContents,
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
  try {
    return await openDialog(sender, options)
  } catch (err) {
    console.error('[electron] Import picker failed:', err)
    return []
  }
}
