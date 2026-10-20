// Native folder and file pickers: the library's folders (setup and Settings) and local
// imports. main.ts registers the IPC that opens them; each picker opens over the window
// that asked, or on its own if that window has gone.
import { app, BrowserWindow, dialog } from 'electron'
import type { FolderKind } from './libraryDirs'

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

const FOLDER_PICKER_TITLES: Record<FolderKind, string> = {
  appData: 'Choose Search Data Folder',
  store: 'Choose Imported Images Folder',
  linked: 'Choose Your Images Folder',
}

/** One of the library's folders (design/library-setup.md). A plain picker: the setup
 * wizard and Settings check the choice with the backend. Null when cancelled, and when the
 * dialog fails: the user can just try again. */
export async function pickLibraryFolder(
  sender: Electron.WebContents,
  kind: FolderKind,
  defaultPath?: string,
): Promise<string | null> {
  try {
    const paths = await openDialog(sender, {
      title: FOLDER_PICKER_TITLES[kind],
      // Electron 43+ opens dialogs in Downloads unless given a starting folder.
      defaultPath: defaultPath ?? app.getPath('home'),
      properties: ['openDirectory', 'createDirectory'],
      buttonLabel: 'Select Folder',
    })
    return paths[0] ?? null
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
