import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, waitFor, within, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test/renderWithProviders'
import EditGroupDialog from './EditGroupDialog'
import type { GroupDetail, GroupSummary, Image } from '@/types'

vi.mock('@/lib/api', () => ({
  groupApi: {
    get: vi.fn(),
    summaries: vi.fn(),
    details: vi.fn(),
    edit: vi.fn().mockResolvedValue({ new_group_ids: [] }),
    delete: vi.fn().mockResolvedValue(undefined),
    merge: vi.fn().mockResolvedValue(undefined),
    moveImages: vi.fn().mockResolvedValue({ source_group_deleted: false }),
    search: vi.fn().mockResolvedValue({ groups: [], total: 0 }),
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

function makeImage(id: number, overrides: Partial<Image> = {}): Image {
  return {
    id,
    storage_key: `${id}.webp`,
    filename: `map_${id}.png`,
    author: 'Cartographer',
    name: `Map ${id}`,
    group_id: 1,
    group_name: 'Forest Maps',
    group_image_count: null,
    created_at: '',
    updated_at: '',
    file_size: 1,
    width: 1,
    height: 1,
    gridded: null,
    grid_width: null,
    grid_height: null,
    grid_type: null,
    grid_confidence: null,
    subgroup: null,
    image_type: 'battlemap',
    thumbnail_key: null,
    media_type: 'image',
    tags: [],
    colors: [],
    ...overrides,
  }
}

const GROUPS: Record<number, GroupDetail> = {
  1: {
    id: 1,
    base_name: 'Forest Maps',
    author: 'Cartographer',
    primary_image_id: 11,
    images: [
      makeImage(11, { name: 'Clearing', subgroup: 'summer' }),
      makeImage(12, { name: 'Brook', subgroup: 'summer' }),
      makeImage(13, { name: 'Frost', subgroup: 'winter' }),
    ],
  },
  2: {
    id: 2,
    base_name: 'Cave Maps',
    author: 'Cartographer',
    primary_image_id: 21,
    images: [makeImage(21, { name: 'Grotto', group_id: 2 })],
  },
  3: {
    id: 3,
    base_name: 'Town Maps',
    author: 'Someone Else',
    primary_image_id: 31,
    images: [makeImage(31, { name: 'Market', group_id: 3 })],
  },
}

function summaryOf(g: GroupDetail): GroupSummary {
  return {
    id: g.id,
    base_name: g.base_name,
    author: g.author,
    primary_image_id: g.primary_image_id,
    image_count: g.images.length,
    image_ids: g.images.map((img) => img.id),
  }
}

/** Make details for any batch holding `slowId` wait until the returned release is called. */
function holdDetailsFor(slowId: number) {
  let release: () => void = () => {}
  vi.mocked(groupApi.details).mockImplementation((ids) => {
    const result = ids.map((id) => structuredClone(GROUPS[id]))
    if (!ids.includes(slowId)) return Promise.resolve(result)
    return new Promise((resolve) => {
      release = () => resolve(result)
    })
  })
  return () => release()
}

function renderDialog(props: Partial<React.ComponentProps<typeof EditGroupDialog>>) {
  const onClose = vi.fn()
  const onSave = vi.fn()
  const user = userEvent.setup()
  renderWithProviders(<EditGroupDialog open onClose={onClose} onSave={onSave} {...props} />)
  return { user, onClose, onSave }
}

const dialog = () => screen.getByTestId('edit-group-dialog')
const confirmDialog = (title: string) =>
  screen.getByText(title).closest('[role="dialog"]') as HTMLElement
const sidebarRow = (name: string) =>
  within(dialog())
    .getAllByText(name)
    .find((el) => el.closest('.group\\/navrow'))!

describe('EditGroupDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(groupApi.get).mockImplementation(async (id: number) => structuredClone(GROUPS[id]))
    vi.mocked(groupApi.summaries).mockImplementation(async (ids) =>
      ids.filter((id) => GROUPS[id]).map((id) => summaryOf(GROUPS[id])),
    )
    vi.mocked(groupApi.details).mockImplementation(async (ids) =>
      ids.filter((id) => GROUPS[id]).map((id) => structuredClone(GROUPS[id])),
    )
  })

  describe('single group', () => {
    it('shows the group with subgroup headings and no sidebar', async () => {
      renderDialog({ groupId: 1 })
      expect(await within(dialog()).findByText('Clearing')).toBeInTheDocument()
      expect(screen.getByRole('heading', { name: 'Edit Group' })).toBeInTheDocument()
      expect(screen.getByDisplayValue('Forest Maps')).toBeInTheDocument()
      expect(screen.getByTitle('Rename "summer"')).toBeInTheDocument()
      expect(screen.getByTitle('Rename "winter"')).toBeInTheDocument()
      expect(screen.queryByText(/groups$/)).not.toBeInTheDocument()
    })

    it('filters files and reports when nothing matches', async () => {
      const { user } = renderDialog({ groupId: 1 })
      await within(dialog()).findByText('Clearing')
      const filter = screen.getByPlaceholderText('Filter maps…')
      await user.type(filter, 'frost')
      expect(within(dialog()).queryByText('Clearing')).not.toBeInTheDocument()
      expect(within(dialog()).getByText('Frost')).toBeInTheDocument()
      await user.clear(filter)
      await user.type(filter, 'zzz')
      expect(screen.getByText('No files match the current filter')).toBeInTheDocument()
    })

    it('auto-saves the group name on blur', async () => {
      const { user } = renderDialog({ groupId: 1 })
      const name = await screen.findByDisplayValue('Forest Maps')
      await user.clear(name)
      await user.type(name, 'Woodland')
      fireEvent.blur(name)
      await waitFor(() =>
        expect(groupApi.edit).toHaveBeenCalledWith(
          1,
          expect.objectContaining({ base_name: 'Woodland' }),
        ),
      )
    })

    it('saves and closes on Done', async () => {
      const { user, onClose, onSave } = renderDialog({ groupId: 1 })
      await within(dialog()).findByText('Clearing')
      await user.click(screen.getByRole('button', { name: 'Done' }))
      expect(onSave).toHaveBeenCalled()
      expect(onClose).toHaveBeenCalled()
    })

    it('confirms before deleting the group', async () => {
      const { user, onClose, onSave } = renderDialog({ groupId: 1 })
      await within(dialog()).findByText('Clearing')
      await user.click(screen.getByRole('button', { name: /Delete Group/ }))
      expect(screen.getByText('Delete this group and all its images?')).toBeInTheDocument()
      await user.click(screen.getByRole('button', { name: 'Cancel' }))
      expect(screen.queryByText('Delete this group and all its images?')).not.toBeInTheDocument()

      await user.click(screen.getByRole('button', { name: /Delete Group/ }))
      await user.click(screen.getByRole('button', { name: 'Confirm' }))
      await waitFor(() => expect(groupApi.delete).toHaveBeenCalledWith(1))
      expect(onSave).toHaveBeenCalled()
      expect(onClose).toHaveBeenCalled()
    })

    it('merges into the group picked in the merge picker', async () => {
      vi.mocked(groupApi.search).mockResolvedValue({
        groups: [
          { id: 2, base_name: 'Cave Maps', author: null, primary_image_id: null, image_count: 1 },
        ],
        total: 1,
      })
      const { user, onClose } = renderDialog({ groupId: 1 })
      await within(dialog()).findByText('Clearing')
      await user.click(screen.getByRole('button', { name: /Merge into/ }))
      await user.click(await screen.findByText('Cave Maps'))
      await user.click(screen.getByRole('button', { name: 'Merge' }))
      await waitFor(() => expect(groupApi.merge).toHaveBeenCalledWith(1, 2))
      expect(groupApi.merge).toHaveBeenCalledTimes(1)
      await waitFor(() => expect(onClose).toHaveBeenCalled())
    })

    it('closes on Escape without saving', async () => {
      const { user, onClose, onSave } = renderDialog({ groupIds: [1] })
      await waitFor(() => expect(groupApi.details).toHaveBeenCalledWith([1]))
      await user.keyboard('{Escape}')
      expect(onClose).toHaveBeenCalled()
      expect(onSave).not.toHaveBeenCalled()
    })
  })

  describe('several groups', () => {
    it('renders only the rows on screen when All holds many files', async () => {
      const big: GroupDetail = {
        id: 4,
        base_name: 'Big Pack',
        author: 'Cartographer',
        primary_image_id: 400,
        images: Array.from({ length: 70 }, (_, i) =>
          makeImage(400 + i, { name: `Big ${i}`, group_id: 4 }),
        ),
      }
      const all: Record<number, GroupDetail> = { ...GROUPS, 4: big }
      vi.mocked(groupApi.summaries).mockImplementation(async (ids) =>
        ids.map((id) => summaryOf(all[id])),
      )
      vi.mocked(groupApi.details).mockImplementation(async (ids) =>
        ids.map((id) => structuredClone(all[id])),
      )
      // jsdom has no layout: give the scroll area a height so the list has a window
      const size = { width: 800, height: 600, top: 0, left: 0, right: 800, bottom: 600 }
      const rect = vi
        .spyOn(HTMLElement.prototype, 'getBoundingClientRect')
        .mockReturnValue({ ...size, x: 0, y: 0, toJSON: () => size } as DOMRect)
      const height = vi.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockReturnValue(600)
      const width = vi.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockReturnValue(800)
      try {
        renderDialog({ groupIds: [1, 4] })
        // Unlabelled files come first, so the summer/winter subgroups are off screen
        expect(await within(dialog()).findByText('Big 0')).toBeInTheDocument()
        expect(within(dialog()).queryByText('Clearing')).not.toBeInTheDocument()
        const shown = within(dialog()).queryAllByText(/^(Big \d+|Clearing|Brook|Frost)$/)
        expect(shown.length).toBeGreaterThan(0)
        expect(shown.length).toBeLessThan(73)
        expect(within(dialog()).queryByText('Big 69')).not.toBeInTheDocument()
      } finally {
        rect.mockRestore()
        height.mockRestore()
        width.mockRestore()
      }
    })

    it('lists groups in the sidebar and switches between them', async () => {
      const { user } = renderDialog({ groupIds: [1, 2] })
      expect(await screen.findByText('2 groups')).toBeInTheDocument()
      // The All tab shows every in-scope file
      expect(within(dialog()).getByText('Grotto')).toBeInTheDocument()
      expect(within(dialog()).getByText('Clearing')).toBeInTheDocument()

      await user.click(sidebarRow('Cave Maps'))
      expect(screen.getByDisplayValue('Cave Maps')).toBeInTheDocument()
      expect(within(dialog()).queryByText('Clearing')).not.toBeInTheDocument()
    })

    it('starts fresh when reopened for a different import', async () => {
      const onClose = vi.fn()
      const { rerender } = renderWithProviders(
        <EditGroupDialog open groupIds={[1, 2]} onClose={onClose} onSave={vi.fn()} />,
      )
      expect(await screen.findByText('2 groups')).toBeInTheDocument()
      rerender(<EditGroupDialog open={false} onClose={onClose} onSave={vi.fn()} />)
      rerender(<EditGroupDialog open groupIds={[3]} onClose={onClose} onSave={vi.fn()} />)
      expect(await screen.findByDisplayValue('Town Maps')).toBeInTheDocument()
      expect(screen.queryByText(/groups/)).not.toBeInTheDocument()
      expect(within(dialog()).queryByText('Clearing')).not.toBeInTheDocument()
    })

    it('opens on the group it was asked to start on', async () => {
      renderDialog({ groupIds: [1, 2, 3], startGroupId: 2 })
      expect(await screen.findByDisplayValue('Cave Maps')).toBeInTheDocument()
      expect(within(dialog()).queryByText('Clearing')).not.toBeInTheDocument()
    })

    it('lists every group at once and fills them in as they load', async () => {
      // Group 3 is slow; the editor opens on the start group without it
      const releaseSlow = holdDetailsFor(3)
      const { user } = renderDialog({ groupIds: [1, 2, 3], startGroupId: 1 })
      expect(await screen.findByDisplayValue('Forest Maps')).toBeInTheDocument()
      expect(screen.getByText('1 of 3 groups')).toBeInTheDocument()
      // Still loading, but already listed from its summary
      expect(screen.getByRole('button', { name: /Town Maps/ })).toHaveAttribute(
        'title',
        expect.stringMatching(/Still loading/),
      )
      await user.click(screen.getByRole('button', { name: /^All\s*\d+$/ }))
      expect(
        screen.getByText(/Changes here apply to the groups already loaded/),
      ).toBeInTheDocument()
      releaseSlow()
      expect(await screen.findByText('3 groups')).toBeInTheDocument()
      expect(sidebarRow('Town Maps')).toBeInTheDocument()
      expect(screen.queryByText(/Still loading/)).not.toBeInTheDocument()
    })

    it('opens a still-loading group as soon as it arrives when clicked', async () => {
      const releaseSlow = holdDetailsFor(3)
      const { user } = renderDialog({ groupIds: [1, 2, 3], startGroupId: 1 })
      await screen.findByDisplayValue('Forest Maps')
      await user.click(screen.getByRole('button', { name: /Town Maps/ }))
      expect(screen.getByRole('button', { name: /Town Maps/ })).toHaveAttribute('aria-busy', 'true')
      releaseSlow()
      expect(await screen.findByDisplayValue('Town Maps')).toBeInTheDocument()
    })

    it('leaves out groups deleted since the import', async () => {
      renderDialog({ groupIds: [1, 99, 2] })
      expect(await screen.findByText('2 groups')).toBeInTheDocument()
    })

    it('merges all groups into the first after confirmation', async () => {
      const { user } = renderDialog({ groupIds: [1, 2] })
      await screen.findByText('2 groups')
      await user.click(screen.getByRole('button', { name: 'Merge All' }))
      const confirm = confirmDialog('Merge All Groups')
      expect(confirm).toHaveTextContent('merge all 2 groups into "Forest Maps"')
      await user.click(within(confirm).getByRole('button', { name: 'Merge All' }))
      await waitFor(() => expect(groupApi.merge).toHaveBeenCalledWith(2, 1))
      await waitFor(() => expect(screen.queryByText('Merge All Groups')).not.toBeInTheDocument())
    })

    it('deletes a group from its row menu after inline confirmation', async () => {
      const { user } = renderDialog({ groupIds: [1, 2] })
      await screen.findByText('2 groups')
      const row = sidebarRow('Cave Maps').closest('.group\\/navrow') as HTMLElement
      await user.click(within(row).getAllByRole('button')[1])
      await user.click(screen.getByRole('menuitem', { name: /Delete group/ }))
      expect(screen.getByText('Delete this group?')).toBeInTheDocument()
      await user.click(screen.getByRole('button', { name: 'Delete' }))
      await waitFor(() => expect(groupApi.delete).toHaveBeenCalledWith(2))
      await waitFor(() => expect(screen.queryByText('Delete this group?')).not.toBeInTheDocument())
    })

    it('merges a group picked from its row menu', async () => {
      vi.mocked(groupApi.search).mockResolvedValue({
        groups: [
          { id: 1, base_name: 'Forest Maps', author: null, primary_image_id: null, image_count: 3 },
        ],
        total: 1,
      })
      const { user } = renderDialog({ groupIds: [1, 2, 3] })
      await screen.findByText('3 groups')
      const row = sidebarRow('Town Maps').closest('.group\\/navrow') as HTMLElement
      await user.click(within(row).getAllByRole('button')[1])
      await user.click(screen.getByRole('menuitem', { name: /Merge into/ }))
      const picker = confirmDialog('Merge into Group')
      await user.click(await within(picker).findByText('Forest Maps'))
      await user.click(within(picker).getByRole('button', { name: 'Merge' }))
      await waitFor(() => expect(groupApi.merge).toHaveBeenCalledWith(3, 1))
      expect(await screen.findByText('2 groups')).toBeInTheDocument()
    })

    it('keeps the inline delete confirmation open when the delete fails', async () => {
      vi.mocked(groupApi.delete).mockRejectedValueOnce(new Error('Group is locked'))
      const { user } = renderDialog({ groupIds: [1, 2] })
      await screen.findByText('2 groups')
      const row = sidebarRow('Cave Maps').closest('.group\\/navrow') as HTMLElement
      await user.click(within(row).getAllByRole('button')[1])
      await user.click(screen.getByRole('menuitem', { name: /Delete group/ }))
      await user.click(screen.getByRole('button', { name: 'Delete' }))
      expect(await screen.findByText('Group is locked')).toBeInTheDocument()
      expect(screen.getByText('Delete this group?')).toBeInTheDocument()
    })

    it('removes a group from view without touching the server', async () => {
      const { user } = renderDialog({ groupIds: [1, 2, 3] })
      await screen.findByText('3 groups')
      const row = sidebarRow('Town Maps').closest('.group\\/navrow') as HTMLElement
      await user.click(within(row).getAllByRole('button')[1])
      await user.click(screen.getByRole('menuitem', { name: /Remove from view/ }))
      expect(await screen.findByText('2 groups')).toBeInTheDocument()
      expect(groupApi.delete).not.toHaveBeenCalled()
    })

    it('bulk merges and deletes ctrl-selected groups', async () => {
      const { user } = renderDialog({ groupIds: [1, 2, 3] })
      await screen.findByText('3 groups')
      await user.keyboard('{Control>}')
      await user.click(sidebarRow('Cave Maps'))
      await user.click(sidebarRow('Town Maps'))
      await user.keyboard('{/Control}')
      expect(screen.getByText('2 selected')).toBeInTheDocument()

      await user.click(screen.getByRole('button', { name: 'Delete' }))
      const del = confirmDialog('Delete Selected Groups')
      expect(del).toHaveTextContent('permanently delete 2 groups')
      await user.click(within(del).getByRole('button', { name: 'Cancel' }))

      await user.click(screen.getByRole('button', { name: 'Merge' }))
      const merge = confirmDialog('Merge Selected Groups')
      expect(merge).toHaveTextContent('merge 2 selected groups into "Cave Maps"')
      await user.click(within(merge).getByRole('button', { name: 'Merge Selected' }))
      await waitFor(() => expect(groupApi.merge).toHaveBeenCalledWith(3, 2))
    })
  })

  describe('search results (mass edit)', () => {
    it('summarises scope and marks other images as out of scope', async () => {
      const { user } = renderDialog({
        seedImages: [
          { id: 11, group_id: 1 },
          { id: 21, group_id: 2 },
          { id: 99, group_id: null },
        ],
      })
      expect(
        await screen.findByRole('heading', { name: 'Edit Search Results' }),
      ).toBeInTheDocument()
      expect(screen.getByText(/2 images across 2 groups · 1 ungrouped skipped/)).toBeInTheDocument()

      await user.click(sidebarRow('Forest Maps'))
      expect(screen.getByText('Other images in this group')).toBeInTheDocument()
      expect(within(dialog()).getByText('Frost')).toBeInTheDocument()
    })
  })
})
