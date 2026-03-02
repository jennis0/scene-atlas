import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useEditGroupOperations } from './useEditGroupOperations'
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
    skip: false,
    status: 'pending',
    processed: 0,
    failed: 0,
    total: 0,
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
