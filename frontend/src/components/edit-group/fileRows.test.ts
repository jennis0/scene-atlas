import { describe, expect, it } from 'vitest'
import type { EditableFileState } from '@/types'
import { buildFileRows } from './fileRows'

const file = (id: number, subgroup: string | null = null) =>
  ({ relative_path: String(id), subgroup }) as EditableFileState

describe('buildFileRows', () => {
  it('pairs files into rows, with no headings for a single subgroup', () => {
    const rows = buildFileRows([file(1), file(2), file(3)], [null])
    expect(rows.map((r) => r.kind)).toEqual(['cards', 'cards'])
    expect(rows.map((r) => r.files.map((f) => f.relative_path))).toEqual([['1', '2'], ['3']])
  })

  it('heads each subgroup, in the given order, and never pairs across subgroups', () => {
    const files = [file(1, 'night'), file(2), file(3, 'night'), file(4, 'night')]
    const rows = buildFileRows(files, [null, 'night'])
    expect(rows.map((r) => [r.kind, r.files.map((f) => f.relative_path)])).toEqual([
      ['heading', ['2']],
      ['cards', ['2']],
      ['heading', ['1', '3', '4']],
      ['cards', ['1', '3']],
      ['cards', ['4']],
    ])
  })

  it('gives every row a unique key', () => {
    const files = Array.from({ length: 9 }, (_, i) => file(i, i % 2 ? 'a' : null))
    const keys = buildFileRows(files, [null, 'a']).map((r) => r.key)
    expect(new Set(keys).size).toBe(keys.length)
  })
})
