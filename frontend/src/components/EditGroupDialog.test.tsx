import { describe, it, expect, vi, beforeEach } from 'vitest'
import { waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test/renderWithProviders'
import EditGroupDialog from './EditGroupDialog'

// ── API mocks ─────────────────────────────────────────────────────────────────

vi.mock('@/lib/api', () => ({
  groupApi: {
    get: vi.fn().mockResolvedValue({
      id: 1,
      base_name: 'Forest Maps',
      author: 'Test Author',
      images: [],
    }),
    edit: vi.fn().mockResolvedValue({ new_group_ids: [] }),
    delete: vi.fn().mockResolvedValue(undefined),
    merge: vi.fn().mockResolvedValue(undefined),
    moveImages: vi.fn().mockResolvedValue({ source_group_deleted: false }),
    confirmReview: vi.fn().mockResolvedValue({ updated: 1 }),
  },
  tagApi: {
    getCategories: vi.fn().mockResolvedValue([]),
  },
  imageApi: {
    getAuthors: vi.fn().mockResolvedValue([]),
  },
  getThumbnailUrlById: vi.fn((id: number) => `/api/v1/images/${id}/thumbnail`),
  getImageUrlById: vi.fn((id: number) => `/api/v1/images/${id}`),
}))

import { groupApi } from '@/lib/api'

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('EditGroupDialog — import-review mode', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('does NOT call confirmReview when dialog is dismissed via Escape', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    const onSave = vi.fn()

    renderWithProviders(
      <EditGroupDialog groupIds={[1]} open onClose={onClose} onSave={onSave} />,
    )

    // Wait for data load to complete (groupApi.get is called on mount)
    await waitFor(() => {
      expect(groupApi.get).toHaveBeenCalledWith(1)
    })

    // Dismiss via Escape key (triggers onOpenChange(false))
    await user.keyboard('{Escape}')

    // Escape should close the dialog (call onClose) but must NOT confirm the import
    expect(onClose).toHaveBeenCalled()
    expect(groupApi.confirmReview).not.toHaveBeenCalled()
    // onSave also must not be called — the import remains unreviewed
    expect(onSave).not.toHaveBeenCalled()
  })
})
