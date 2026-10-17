import { describe, it, expect, vi } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useFileEditing, ALL_GROUP_ID, MULTI_GROUP_ID } from './useFileEditing'
import type { EditableFileState, EditableGroupState } from '@/types'

// ── Fixtures ──────────────────────────────────────────────────────────────────

function makeFile(overrides: Partial<EditableFileState> = {}): EditableFileState {
  return {
    relative_path: 'forest.jpg',
    filename: 'forest.jpg',
    name: 'forest',
    tags: [],
    gridded: null,
    grid_width: null,
    grid_height: null,
    grid_type: null,
    subgroup: null,
    image_type: 'battlemap',
    excluded: false,
    ...overrides,
  }
}

function makeGroup(overrides: Partial<EditableGroupState> = {}): EditableGroupState {
  return {
    id: 'group-1',
    author: 'Author A',
    group_name: 'Test Group',
    files: [makeFile()],
    ...overrides,
  }
}

// ── CRUD ──────────────────────────────────────────────────────────────────────

describe('useFileEditing — CRUD', () => {
  it('updateGroup updates group by ID', () => {
    const { result } = renderHook(() => useFileEditing())

    act(() => {
      result.current.setGroups([makeGroup(), makeGroup({ id: 'group-2', author: 'Author B' })])
    })

    act(() => {
      result.current.updateGroup('group-1', { author: 'Updated Author' })
    })

    expect(result.current.groups[0].author).toBe('Updated Author')
    expect(result.current.groups[1].author).toBe('Author B')
  })

  it('updateFile updates file by relativePath within a group', () => {
    const file1 = makeFile({ relative_path: 'a.jpg', name: 'a' })
    const file2 = makeFile({ relative_path: 'b.jpg', name: 'b' })
    const { result } = renderHook(() => useFileEditing())

    act(() => {
      result.current.setGroups([makeGroup({ files: [file1, file2] })])
    })

    act(() => {
      result.current.updateFile(0, 'b.jpg', { name: 'updated' })
    })

    expect(result.current.groups[0].files[0].name).toBe('a')
    expect(result.current.groups[0].files[1].name).toBe('updated')
  })

  it('updateFile fires onGroupChange callback', () => {
    const onGroupChange = vi.fn()
    const { result } = renderHook(() => useFileEditing({ onGroupChange }))

    act(() => {
      result.current.setGroups([makeGroup()])
    })

    act(() => {
      result.current.updateFile(0, 'forest.jpg', { name: 'updated' })
    })

    expect(onGroupChange).toHaveBeenCalledTimes(1)
    expect(onGroupChange).toHaveBeenCalledWith(
      expect.arrayContaining([expect.objectContaining({ id: 'group-1' })]),
    )
  })

  it('updateFile rapid successive calls on different files both persist', () => {
    const file1 = makeFile({ relative_path: 'a.jpg', name: 'a' })
    const file2 = makeFile({ relative_path: 'b.jpg', name: 'b' })
    const { result } = renderHook(() => useFileEditing())

    act(() => {
      result.current.setGroups([makeGroup({ files: [file1, file2] })])
    })

    // Call updateFile twice in the same act() — without functional updater,
    // the second call would read stale `groups` and overwrite the first.
    act(() => {
      result.current.updateFile(0, 'a.jpg', { name: 'updated-a' })
      result.current.updateFile(0, 'b.jpg', { name: 'updated-b' })
    })

    expect(result.current.groups[0].files[0].name).toBe('updated-a')
    expect(result.current.groups[0].files[1].name).toBe('updated-b')
  })

  it('updateFileAnyGroup updates file across all groups', () => {
    const file = makeFile({ relative_path: 'shared.jpg' })
    const { result } = renderHook(() => useFileEditing())

    act(() => {
      result.current.setGroups([
        makeGroup({ id: 'g1', files: [file] }),
        makeGroup({ id: 'g2', files: [makeFile({ relative_path: 'other.jpg' })] }),
      ])
    })

    act(() => {
      result.current.updateFileAnyGroup('shared.jpg', { name: 'renamed' })
    })

    expect(result.current.groups[0].files[0].name).toBe('renamed')
    expect(result.current.groups[1].files[0].name).toBe('forest') // unchanged (default name)
  })
})

// ── Selection ─────────────────────────────────────────────────────────────────

describe('useFileEditing — Selection', () => {
  it('toggleFileSelection adds and removes files', () => {
    const { result } = renderHook(() => useFileEditing())

    act(() => {
      result.current.toggleFileSelection('g1', 'a.jpg')
    })
    expect(result.current.selections['g1']?.has('a.jpg')).toBe(true)

    act(() => {
      result.current.toggleFileSelection('g1', 'a.jpg')
    })
    expect(result.current.selections['g1']?.has('a.jpg')).toBe(false)
  })

  it('selectAllVisible adds non-excluded, non-outOfScope files', () => {
    const files = [
      makeFile({ relative_path: 'a.jpg' }),
      makeFile({ relative_path: 'b.jpg', excluded: true }),
      makeFile({ relative_path: 'c.jpg', outOfScope: true }),
      makeFile({ relative_path: 'd.jpg' }),
    ]
    const { result } = renderHook(() => useFileEditing())

    act(() => {
      result.current.selectAllVisible('g1', files)
    })

    const sel = result.current.selections['g1']!
    expect(sel.has('a.jpg')).toBe(true)
    expect(sel.has('b.jpg')).toBe(false)
    expect(sel.has('c.jpg')).toBe(false)
    expect(sel.has('d.jpg')).toBe(true)
  })

  it('deselectAll clears selection for a group', () => {
    const { result } = renderHook(() => useFileEditing())

    act(() => {
      result.current.toggleFileSelection('g1', 'a.jpg')
      result.current.toggleFileSelection('g1', 'b.jpg')
    })

    act(() => {
      result.current.deselectAll('g1')
    })

    expect(result.current.selections['g1']?.size).toBe(0)
  })
})

// ── Bulk operations ───────────────────────────────────────────────────────────

describe('useFileEditing — Bulk ops', () => {
  function setupBulk() {
    const onGroupChange = vi.fn()
    const hook = renderHook(() => useFileEditing({ onGroupChange }))

    const files = [
      makeFile({ relative_path: 'a.jpg' }),
      makeFile({ relative_path: 'b.jpg' }),
      makeFile({ relative_path: 'c.jpg', excluded: true }),
    ]

    act(() => {
      hook.result.current.setGroups([makeGroup({ id: 'g1', files })])
    })
    // Select a.jpg and b.jpg (c.jpg is excluded)
    act(() => {
      hook.result.current.toggleFileSelection('g1', 'a.jpg')
      hook.result.current.toggleFileSelection('g1', 'b.jpg')
      hook.result.current.toggleFileSelection('g1', 'c.jpg')
    })

    return { hook, onGroupChange }
  }

  it('selectedInScope lists the selected files that are not excluded', () => {
    const { hook } = setupBulk()
    const paths = hook.result.current.selectedInScope('g1').map((f) => f.relative_path)
    expect(paths).toEqual(['a.jpg', 'b.jpg'])
  })

  it('patchFiles changes files without saving their groups', async () => {
    const { hook, onGroupChange } = setupBulk()
    onGroupChange.mockClear()
    act(() => {
      hook.result.current.patchFiles(new Set(['b.jpg']), (f) => ({ ...f, image_type: 'scene' }))
    })
    const types = hook.result.current.groups[0].files.map((f) => f.image_type)
    expect(types).toEqual(['battlemap', 'scene', 'battlemap'])
    expect(onGroupChange).not.toHaveBeenCalled()
  })

  it('applies a multi-group scope to the multi-select selection only', () => {
    const { result } = renderHook(() => useFileEditing())
    act(() => {
      result.current.setGroups([
        makeGroup({ id: 'g1', files: [makeFile({ relative_path: 'a.jpg' })] }),
        makeGroup({ id: 'g2', files: [makeFile({ relative_path: 'b.jpg' })] }),
        makeGroup({ id: 'g3', files: [makeFile({ relative_path: 'c.jpg' })] }),
      ])
    })
    act(() => {
      result.current.toggleFileSelection(MULTI_GROUP_ID, 'a.jpg')
      result.current.toggleFileSelection(MULTI_GROUP_ID, 'c.jpg')
    })
    expect(result.current.selectedInScope(['g1', 'g2']).map((f) => f.relative_path)).toEqual([
      'a.jpg',
    ])

    act(() => {
      result.current.bulkExclude(['g1', 'g3'])
    })
    expect(result.current.groups.map((g) => g.files[0].excluded)).toEqual([true, false, true])
    expect(result.current.selections[MULTI_GROUP_ID]?.size ?? 0).toBe(0)
  })

  it('bulkExclude excludes selected files and clears selection', () => {
    const { hook } = setupBulk()

    act(() => {
      hook.result.current.bulkExclude('g1')
    })

    const files = hook.result.current.groups[0].files
    expect(files[0].excluded).toBe(true)
    expect(files[1].excluded).toBe(true)
    expect(hook.result.current.selections['g1']?.size).toBe(0)
  })
})

// ── Subgroup ops ──────────────────────────────────────────────────────────────

describe('useFileEditing — Subgroup ops', () => {
  it('clearSubgroupLabel nulls subgroup for matching files', () => {
    const files = [
      makeFile({ relative_path: 'a.jpg', subgroup: 'day' }),
      makeFile({ relative_path: 'b.jpg', subgroup: 'night' }),
      makeFile({ relative_path: 'c.jpg', subgroup: 'day', excluded: true }),
    ]
    const { result } = renderHook(() => useFileEditing())

    act(() => {
      result.current.setGroups([makeGroup({ id: 'g1', files })])
    })

    act(() => {
      result.current.clearSubgroupLabel('g1', 'day')
    })

    expect(result.current.groups[0].files[0].subgroup).toBeNull()
    expect(result.current.groups[0].files[1].subgroup).toBe('night')
    expect(result.current.groups[0].files[2].subgroup).toBe('day') // excluded — untouched
  })

  it('renameSubgroup renames matching subgroup values', () => {
    const files = [
      makeFile({ relative_path: 'a.jpg', subgroup: 'old-name' }),
      makeFile({ relative_path: 'b.jpg', subgroup: 'other' }),
    ]
    const { result } = renderHook(() => useFileEditing())

    act(() => {
      result.current.setGroups([makeGroup({ id: 'g1', files })])
    })

    act(() => {
      result.current.renameSubgroup('g1', 'old-name', '  new-name  ')
    })

    expect(result.current.groups[0].files[0].subgroup).toBe('new-name')
    expect(result.current.groups[0].files[1].subgroup).toBe('other')
  })

  it('renameSubgroup to empty string sets null', () => {
    const files = [makeFile({ relative_path: 'a.jpg', subgroup: 'val' })]
    const { result } = renderHook(() => useFileEditing())

    act(() => {
      result.current.setGroups([makeGroup({ id: 'g1', files })])
    })

    act(() => {
      result.current.renameSubgroup('g1', 'val', '   ')
    })

    expect(result.current.groups[0].files[0].subgroup).toBeNull()
  })
})

// ── Derived values ────────────────────────────────────────────────────────────

describe('useFileEditing — Derived values', () => {
  it('isAllTab is true when activeTab is ALL_TAB', () => {
    const { result } = renderHook(() => useFileEditing())
    expect(result.current.isAllTab).toBe(true)
    expect(result.current.activeGroupId).toBe(ALL_GROUP_ID)
  })

  it('activeGroup returns the group at activeTab index', () => {
    const { result } = renderHook(() => useFileEditing())

    act(() => {
      result.current.setGroups([makeGroup({ id: 'g1' }), makeGroup({ id: 'g2' })])
    })

    act(() => {
      result.current.setActiveTab(1)
    })

    expect(result.current.isAllTab).toBe(false)
    expect(result.current.activeGroup?.id).toBe('g2')
    expect(result.current.activeGroupId).toBe('g2')
  })
})
