/**
 * Async traversal of DataTransfer items using the FileSystemEntry API.
 * Supports any mix of dropped individual files and folders (arbitrarily nested).
 */

function fileFromEntry(entry: FileSystemFileEntry): Promise<File> {
  return new Promise((resolve, reject) => entry.file(resolve, reject))
}

/**
 * Read ALL entries from a directory reader, calling readEntries repeatedly
 * until an empty batch is returned. Most browsers cap each call at 100 items.
 */
async function readAllEntries(reader: FileSystemDirectoryReader): Promise<FileSystemEntry[]> {
  const all: FileSystemEntry[] = []
  // eslint-disable-next-line no-constant-condition
  while (true) {
    const batch = await new Promise<FileSystemEntry[]>((resolve, reject) =>
      reader.readEntries(resolve, reject),
    )
    if (batch.length === 0) break
    all.push(...batch)
  }
  return all
}

async function traverseEntry(
  entry: FileSystemEntry,
  pathPrefix: string,
  results: Array<{ file: File; relativePath: string }>,
): Promise<void> {
  if (entry.isFile) {
    const file = await fileFromEntry(entry as FileSystemFileEntry)
    results.push({ file, relativePath: pathPrefix + entry.name })
  } else if (entry.isDirectory) {
    const entries = await readAllEntries((entry as FileSystemDirectoryEntry).createReader())
    await Promise.all(
      entries.map((child) => traverseEntry(child, pathPrefix + entry.name + '/', results)),
    )
  }
}

/**
 * Collect all files from a drop event's DataTransfer, traversing any nested
 * folder structures. Returns { file, relativePath } pairs where relativePath
 * matches the format produced by input[webkitdirectory]
 * (e.g. "FolderName/subfolder/image.jpg" or just "image.jpg" for top-level files).
 *
 * Strategy:
 * 1. Try FileSystemEntry API (webkitGetAsEntry) — supports folder traversal in
 *    standard browsers and most Electron builds.
 * 2. Fall back to dataTransfer.files — always works in Electron for native OS
 *    file drops where webkitGetAsEntry() returns null.
 *
 * IMPORTANT: DataTransfer entries must be extracted synchronously before any
 * awaits — the DataTransfer object is invalidated after the event handler returns.
 */
export async function collectFilesFromDataTransfer(
  dataTransfer: DataTransfer,
): Promise<Array<{ file: File; relativePath: string }>> {
  // Extract entries synchronously while the DataTransfer is still valid
  const entries: FileSystemEntry[] = []
  for (let i = 0; i < dataTransfer.items.length; i++) {
    const item = dataTransfer.items[i]
    if (item.kind !== 'file') continue
    const entry = item.webkitGetAsEntry?.()
    if (entry) entries.push(entry)
  }

  // Primary path: FileSystemEntry API (supports nested folder traversal)
  if (entries.length > 0) {
    const results: Array<{ file: File; relativePath: string }> = []
    await Promise.all(entries.map((entry) => traverseEntry(entry, '', results)))
    return results
  }

  // Fallback: Electron native OS drops — webkitGetAsEntry() returns null but
  // dataTransfer.files is always populated. File objects in Electron have a
  // native `path` property. For directory drops (size=0, type=''), we use IPC
  // to traverse the directory and read each file's bytes.
  const electronAPI = window.electronAPI
  if (electronAPI?.readDirectory && electronAPI?.readFileBytes) {
    const results: Array<{ file: File; relativePath: string }> = []
    for (const dropped of Array.from(dataTransfer.files)) {
      const nativePath = (dropped as File & { path?: string }).path
      if (nativePath && dropped.size === 0 && dropped.type === '') {
        // Likely a directory — traverse it via IPC
        const entries = await electronAPI.readDirectory(nativePath)
        for (const entry of entries) {
          const { data } = await electronAPI.readFileBytes(entry.absolutePath)
          const filename = entry.relativePath.split('/').pop() ?? entry.relativePath
          // .slice() copies into a concrete ArrayBuffer (required by the File constructor)
          results.push({
            file: new File([data.slice()], filename),
            relativePath: entry.relativePath,
          })
        }
      } else {
        // Regular file — already have a complete File object
        results.push({ file: dropped, relativePath: dropped.name })
      }
    }
    return results
  }

  return Array.from(dataTransfer.files).map((file) => ({
    file,
    relativePath: file.name,
  }))
}
