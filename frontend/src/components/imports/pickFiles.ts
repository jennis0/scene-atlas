/**
 * Turn file inputs and drops into PickedFile lists with relative paths.
 * Paths matter: the server groups files by their folders.
 */

import { collectFilesFromDataTransfer } from '@/lib/fsEntryTraversal'
import type { PickedFile } from '@/lib/import/types'

/** From an <input type="file"> (folder pickers set webkitRelativePath). */
export function filesFromInput(list: FileList | null): PickedFile[] {
  return Array.from(list ?? [], (file) => ({
    file,
    relativePath: file.webkitRelativePath || file.name,
  }))
}

/** From a drop of any mix of files and folders. */
export async function filesFromDrop(dataTransfer: DataTransfer): Promise<PickedFile[]> {
  const collected = await collectFilesFromDataTransfer(dataTransfer)
  return collected.map(({ file, relativePath }) => ({ file, relativePath }))
}
