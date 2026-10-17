import { describe, it, expect } from 'vitest'
import { renderHook } from '@testing-library/react'
import { commonAuthor, useEditScope } from './useEditScope'
import { EMPTY_FILTER } from '@/components/import/fileFilter'
import { ALL_GROUP_ID, MULTI_GROUP_ID } from '@/hooks/useFileEditing'
import type { EditableFileState, EditableGroupState } from '@/types'

const file = (path: string, overrides: Partial<EditableFileState> = {}): EditableFileState => ({
  relative_path: path,
  filename: `${path}.png`,
  name: path,
  tags: [],
  gridded: null,
  grid_width: null,
  grid_height: null,
  grid_type: null,
  subgroup: null,
  excluded: false,
  ...overrides,
})

const groups: EditableGroupState[] = [
  {
    id: '1',
    author: 'A',
    group_name: 'One',
    files: [file('a', { subgroup: 'night' }), file('b', { outOfScope: true })],
  },
  { id: '2', author: 'A', group_name: 'Two', files: [file('c', { subgroup: 'day' })] },
  { id: '3', author: 'B', group_name: 'Three', files: [file('d')] },
]

function scopeFor(opts: { activeGroup?: EditableGroupState | null; selected?: string[] }) {
  const isAllTab = opts.activeGroup === undefined
  return renderHook(() =>
    useEditScope({
      groups,
      activeGroup: opts.activeGroup ?? null,
      activeGroupId: isAllTab ? ALL_GROUP_ID : (opts.activeGroup?.id ?? ''),
      isAllTab,
      selectedGroupIds: new Set(opts.selected ?? []),
      fileFilter: EMPTY_FILTER,
    }),
  ).result.current
}

describe('commonAuthor', () => {
  it('returns the shared author or an empty string', () => {
    expect(commonAuthor(groups.slice(0, 2))).toBe('A')
    expect(commonAuthor(groups)).toBe('')
    expect(commonAuthor([])).toBe('')
  })
})

describe('useEditScope', () => {
  it('covers every group on the All tab, without out-of-scope files', () => {
    const scope = scopeFor({})
    expect(scope.showsMultipleGroups).toBe(true)
    expect(scope.bulkScope).toBeNull()
    expect(scope.inScopeFiles.map((f) => f.relative_path)).toEqual(['a', 'c', 'd'])
    expect(scope.outOfScopeFiles).toEqual([])
    expect(scope.subgroups).toEqual(['day', 'night'])
    expect(scope.scopeAuthor).toBe('')
  })

  it('shows one group with its out-of-scope files for context', () => {
    const scope = scopeFor({ activeGroup: groups[0] })
    expect(scope.showsMultipleGroups).toBe(false)
    expect(scope.bulkScope).toBe('1')
    expect(scope.selectionId).toBe('1')
    expect(scope.inScopeFiles.map((f) => f.relative_path)).toEqual(['a'])
    expect(scope.outOfScopeFiles.map((f) => f.relative_path)).toEqual(['b'])
    expect(scope.scopeAuthor).toBe('A')
  })

  it('narrows to the multi-selected groups', () => {
    const scope = scopeFor({ activeGroup: groups[2], selected: ['1', '2'] })
    expect(scope.isMultiSelect).toBe(true)
    expect(scope.selectionId).toBe(MULTI_GROUP_ID)
    expect(scope.bulkScope).toEqual(['1', '2'])
    expect(scope.inScopeFiles.map((f) => f.relative_path)).toEqual(['a', 'c'])
    expect(scope.scopeAuthor).toBe('A')
    expect(scope.fileGroupIds.get('d')).toBe('3')
  })
})
