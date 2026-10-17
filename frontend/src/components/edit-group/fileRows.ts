import type { EditableFileState } from '@/types'

/** Cards per row in the editor's file grid (`grid-cols-2`) */
export const FILE_GRID_COLUMNS = 2

/** One row of the virtualised file grid: a subgroup heading, or a row of cards under one. */
export type FileRow =
  | { kind: 'heading'; key: string; subgroup: string | null; files: EditableFileState[] }
  | { kind: 'cards'; key: string; subgroup: string | null; files: EditableFileState[] }

/**
 * Flatten the file grid into rows for virtualising. `order` is the subgroup order; with
 * a single subgroup there are no headings, as in the unvirtualised grid. A heading row
 * carries all of its subgroup's files (for its count); a card row carries its own.
 */
export function buildFileRows(
  files: EditableFileState[],
  order: (string | null)[],
  columns = FILE_GRID_COLUMNS,
): FileRow[] {
  const withHeadings = order.length > 1
  const rows: FileRow[] = []
  for (const subgroup of order) {
    const section = files.filter((f) => f.subgroup === subgroup)
    const name = subgroup ?? '__main__'
    if (withHeadings) rows.push({ kind: 'heading', key: `h:${name}`, subgroup, files: section })
    for (let i = 0; i < section.length; i += columns) {
      const cards = section.slice(i, i + columns)
      rows.push({
        kind: 'cards',
        key: `c:${name}:${cards[0].relative_path}`,
        subgroup,
        files: cards,
      })
    }
  }
  return rows
}
