import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useEditGroupOperations } from './useEditGroupOperations'
import { tabAfterRemoval } from './useEditGroupLoad'
import { ALL_TAB } from './useFileEditing'
import type { EditableGroupState } from '@/types'

// ── Mocks ─────────────────────────────────────────────────────────────────────

vi.mock('@/lib/api', () => ({
  groupApi: {
    edit: vi.fn().mockResolvedValue({ new_group_ids: [] }),
    delete: vi.fn().mockResolvedValue(undefined),
    merge: vi.fn().mockResolvedValue(undefined),
    get: vi.fn().mockResolvedValue({ id: 42, base_name: 'Forest', author: '', images: [] }),
    moveImages: vi.fn().mockResolvedValue({ source_group_deleted: false }),
  },
}))

import { groupApi } from '@/lib/api'

// ── Fixtures ───────────────────────────────────────────────────────────────────

function makeGroup(overrides: Partial<EditableGroupState> = {}): EditableGroupState {
  return {
    id: '42',
    author: 'Test Author',
    group_name: 'Forest Maps',
    files: [],
    ...overrides,
  }
}

function makeOptions(overrides: Record<string, unknown> = {}) {
  return {
    groupId: null,
    groups: [],
    setGroups: vi.fn(),
    activeTab: 0,
    setActiveTab: vi.fn(),
    selections: {},
    deselectAll: vi.fn(),
    invalidateGallery: vi.fn(),
    onSave: vi.fn(),
    onClose: vi.fn(),
    ...overrides,
  }
}

// ── autoSaveGroup ─────────────────────────────────────────────────────────────

describe('useEditGroupOperations — autoSaveGroup', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('does not call invalidateGallery after a successful save', async () => {
    const invalidateGallery = vi.fn()
    const { result } = renderHook(() => useEditGroupOperations(makeOptions({ invalidateGallery })))

    await act(async () => {
      await result.current.autoSaveGroup(makeGroup())
    })

    expect(groupApi.edit).toHaveBeenCalledWith(42, expect.any(Object))
    // Gallery invalidation on auto-save resets sidebar to ALL tab — must NOT happen here.
    // It will be triggered by onSave() when the dialog closes instead.
    expect(invalidateGallery).not.toHaveBeenCalled()
  })

  it('skips the API call for locally-created groups (non-numeric ID)', async () => {
    const invalidateGallery = vi.fn()
    const { result } = renderHook(() => useEditGroupOperations(makeOptions({ invalidateGallery })))

    await act(async () => {
      await result.current.autoSaveGroup(makeGroup({ id: 'local-uuid-abc' }))
    })

    expect(groupApi.edit).not.toHaveBeenCalled()
    expect(invalidateGallery).not.toHaveBeenCalled()
  })
})

describe('tabAfterRemoval', () => {
  it('shifts, falls back, or leaves the tab alone', () => {
    expect(tabAfterRemoval(ALL_TAB, 0, 0)).toBe(ALL_TAB)
    expect(tabAfterRemoval(3, 1, 0)).toBe(2)
    expect(tabAfterRemoval(3, 3, 99)).toBe(99)
    expect(tabAfterRemoval(1, 3, 0)).toBe(1)
  })
})

describe('useEditGroupOperations — handleMergeAll', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('merges every group into the first and resyncs after a partial failure', async () => {
    vi.mocked(groupApi.merge)
      .mockResolvedValueOnce(undefined as never)
      .mockRejectedValueOnce(new Error('boom'))
    vi.mocked(groupApi.get).mockResolvedValueOnce({
      id: 1,
      base_name: 'Merged',
      author: 'A',
      images: [],
    } as never)
    const groups = [makeGroup({ id: '1' }), makeGroup({ id: '2' }), makeGroup({ id: '3' })]
    const setGroups = vi.fn()
    const setActiveTab = vi.fn()
    const { result } = renderHook(() =>
      useEditGroupOperations(makeOptions({ groups, setGroups, setActiveTab })),
    )

    await act(async () => {
      await result.current.handleMergeAll()
    })

    expect(groupApi.merge).toHaveBeenCalledWith(2, 1)
    expect(groupApi.merge).toHaveBeenCalledWith(3, 1)
    const kept = setGroups.mock.calls[0][0] as EditableGroupState[]
    expect(kept.map((g) => g.id)).toEqual(['1', '3'])
    expect(kept[0].group_name).toBe('Merged')
    expect(setActiveTab).toHaveBeenCalledWith(ALL_TAB)
    expect(result.current.saveError).toBe('boom')
  })
})

describe('useEditGroupOperations — handleMoveImagesToGroup', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('drops an emptied source group and adjusts the tab outside the groups updater', async () => {
    vi.mocked(groupApi.moveImages).mockResolvedValueOnce({ source_group_deleted: true } as never)
    const groups = [makeGroup({ id: '1' }), makeGroup({ id: '2' }), makeGroup({ id: '3' })]
    const setGroups = vi.fn()
    const setActiveTab = vi.fn()
    const { result } = renderHook(() =>
      useEditGroupOperations(makeOptions({ groups, setGroups, setActiveTab })),
    )

    await act(async () => {
      await result.current.handleMoveImagesToGroup({ id: '7', groupId: '1' }, '3')
    })

    const updater = setGroups.mock.calls[0][0] as (
      prev: EditableGroupState[],
    ) => EditableGroupState[]
    const tabCallsBefore = setActiveTab.mock.calls.length
    expect(updater(groups).map((g) => g.id)).toEqual(['2', '3'])
    expect(setActiveTab.mock.calls.length).toBe(tabCallsBefore) // updater is pure

    const tabUpdater = setActiveTab.mock.calls[0][0] as (prev: number) => number
    expect(tabUpdater(2)).toBe(1)
    expect(tabUpdater(0)).toBe(0)
  })
})

describe('useEditGroupOperations — confirmable operations report success', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('handleDeleteGroup resolves true on success and false on failure', async () => {
    const groups = [makeGroup({ id: '1' }), makeGroup({ id: '2' })]
    const { result } = renderHook(() => useEditGroupOperations(makeOptions({ groups })))

    let ok: boolean | undefined
    await act(async () => {
      ok = await result.current.handleDeleteGroup('2')
    })
    expect(ok).toBe(true)

    vi.mocked(groupApi.delete).mockRejectedValueOnce(new Error('nope'))
    await act(async () => {
      ok = await result.current.handleDeleteGroup('2')
    })
    expect(ok).toBe(false)
    expect(result.current.saveError).toBe('nope')
  })

  it('handleMerge closes the dialog only on success', async () => {
    const onClose = vi.fn()
    const { result } = renderHook(() =>
      useEditGroupOperations(makeOptions({ groupId: 1, onClose })),
    )
    vi.mocked(groupApi.merge).mockRejectedValueOnce(new Error('conflict'))
    let ok: boolean | undefined
    await act(async () => {
      ok = await result.current.handleMerge({ id: 2 })
    })
    expect(ok).toBe(false)
    expect(onClose).not.toHaveBeenCalled()

    await act(async () => {
      ok = await result.current.handleMerge({ id: 2 })
    })
    expect(ok).toBe(true)
    expect(onClose).toHaveBeenCalled()
  })
})
