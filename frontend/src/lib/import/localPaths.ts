/**
 * Desktop app: import files and folders by path instead of uploading them
 * (design/local-ingest.md). The backend lists and reads the paths itself.
 */

/** Whether imports can name paths on this computer (the desktop app). */
export function canImportLocally(): boolean {
  return typeof window !== 'undefined' && typeof window.electronAPI?.getPathForFile === 'function'
}

/**
 * The paths of the dropped files and folders, without walking them, or null
 * unless every one has a path on disk (then the drop is uploaded as before).
 * Call it in the drop handler before any await: the DataTransfer is emptied
 * once the handler returns.
 */
export function pathsFromDrop(dataTransfer: DataTransfer): string[] | null {
  const api = window.electronAPI
  if (!api || !canImportLocally()) return null
  const paths = Array.from(dataTransfer.files, (file) => api.getPathForFile(file))
  if (paths.length === 0 || paths.some((p) => !p)) return null
  return paths
}

/** The native folder or file picker; [] when cancelled or outside the desktop app. */
export async function chooseLocalPaths(kind: 'folders' | 'files'): Promise<string[]> {
  const api = window.electronAPI
  if (!api || !canImportLocally()) return []
  if (kind === 'folders') return api.chooseImportFolders()
  return api.chooseImportFiles()
}
