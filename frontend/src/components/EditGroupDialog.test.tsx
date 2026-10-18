import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { screen, waitFor, within, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test/renderWithProviders'
import { fakeLayout } from '@/test/fakeLayout'
import { installFakeImportManager, item, uninstallFakeImportManager } from '@/test/importFakes'
import type { ImportManager } from '@/lib/import/ImportManager'
import EditGroupDialog from './EditGroupDialog'
import type { GroupDetail, GroupSummary, Image } from '@/types'

vi.mock('@/lib/api', () => ({
  groupApi: {
    get: vi.fn(),
    summaries: vi.fn(),
    details: vi.fn(),
    bulkUpdate: vi.fn().mockResolvedValue(undefined),
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
    bulkEdit: vi.fn(),
    bulkRestore: vi.fn().mockResolvedValue(undefined),
    facets: vi.fn(),
  },
  getThumbnailUrlById: vi.fn((id: number) => `/api/v1/images/${id}/thumbnail`),
  getImageUrlById: vi.fn((id: number) => `/api/v1/images/${id}`),
}))

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

import { toast } from 'sonner'
import { groupApi, imageApi } from '@/lib/api'

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
    map_count: g.images.filter((img) => img.image_type !== 'scene').length,
    scene_count: g.images.filter((img) => img.image_type === 'scene').length,
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
      const { user, onClose, onSave } = renderDialog({ importReview: { groupIds: [1] } })
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
      const restoreLayout = fakeLayout({ width: 800, height: 600 })
      try {
        renderDialog({ importReview: { groupIds: [1, 4] } })
        // Unlabelled files come first, so the summer/winter subgroups are off screen
        expect(await within(dialog()).findByText('Big 0')).toBeInTheDocument()
        expect(within(dialog()).queryByText('Clearing')).not.toBeInTheDocument()
        const shown = within(dialog()).queryAllByText(/^(Big \d+|Clearing|Brook|Frost)$/)
        expect(shown.length).toBeGreaterThan(0)
        expect(shown.length).toBeLessThan(73)
        expect(within(dialog()).queryByText('Big 69')).not.toBeInTheDocument()
      } finally {
        restoreLayout()
      }
    })

    it('lists groups in the sidebar and switches between them', async () => {
      const { user } = renderDialog({ importReview: { groupIds: [1, 2] } })
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
        <EditGroupDialog
          open
          importReview={{ groupIds: [1, 2] }}
          onClose={onClose}
          onSave={vi.fn()}
        />,
      )
      expect(await screen.findByText('2 groups')).toBeInTheDocument()
      rerender(<EditGroupDialog open={false} onClose={onClose} onSave={vi.fn()} />)
      rerender(
        <EditGroupDialog
          open
          importReview={{ groupIds: [3] }}
          onClose={onClose}
          onSave={vi.fn()}
        />,
      )
      expect(await screen.findByDisplayValue('Town Maps')).toBeInTheDocument()
      expect(screen.queryByText(/groups/)).not.toBeInTheDocument()
      expect(within(dialog()).queryByText('Clearing')).not.toBeInTheDocument()
    })

    it('opens on the group it was asked to start on', async () => {
      renderDialog({ importReview: { groupIds: [1, 2, 3], startGroupId: 2 } })
      expect(await screen.findByDisplayValue('Cave Maps')).toBeInTheDocument()
      expect(within(dialog()).queryByText('Clearing')).not.toBeInTheDocument()
    })

    it('lists every group at once and fills them in as they load', async () => {
      // Group 3 is slow; the editor opens on the start group without it
      const releaseSlow = holdDetailsFor(3)
      const { user } = renderDialog({ importReview: { groupIds: [1, 2, 3], startGroupId: 1 } })
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
      const { user } = renderDialog({ importReview: { groupIds: [1, 2, 3], startGroupId: 1 } })
      await screen.findByDisplayValue('Forest Maps')
      await user.click(screen.getByRole('button', { name: /Town Maps/ }))
      expect(screen.getByRole('button', { name: /Town Maps/ })).toHaveAttribute('aria-busy', 'true')
      releaseSlow()
      expect(await screen.findByDisplayValue('Town Maps')).toBeInTheDocument()
    })

    it('leaves out groups deleted since the import', async () => {
      renderDialog({ importReview: { groupIds: [1, 99, 2] } })
      expect(await screen.findByText('2 groups')).toBeInTheDocument()
    })

    it('merges all groups into the first after confirmation', async () => {
      const { user } = renderDialog({ importReview: { groupIds: [1, 2] } })
      await screen.findByText('2 groups')
      await user.click(screen.getByRole('button', { name: 'Merge All' }))
      const confirm = confirmDialog('Merge All Groups')
      expect(confirm).toHaveTextContent('merge all 2 groups into "Forest Maps"')
      await user.click(within(confirm).getByRole('button', { name: 'Merge All' }))
      await waitFor(() => expect(groupApi.merge).toHaveBeenCalledWith(2, 1))
      await waitFor(() => expect(screen.queryByText('Merge All Groups')).not.toBeInTheDocument())
    })

    it('deletes a group from its row menu after inline confirmation', async () => {
      const { user } = renderDialog({ importReview: { groupIds: [1, 2] } })
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
      const { user } = renderDialog({ importReview: { groupIds: [1, 2, 3] } })
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
      const { user } = renderDialog({ importReview: { groupIds: [1, 2] } })
      await screen.findByText('2 groups')
      const row = sidebarRow('Cave Maps').closest('.group\\/navrow') as HTMLElement
      await user.click(within(row).getAllByRole('button')[1])
      await user.click(screen.getByRole('menuitem', { name: /Delete group/ }))
      await user.click(screen.getByRole('button', { name: 'Delete' }))
      expect(await screen.findByText('Group is locked')).toBeInTheDocument()
      expect(screen.getByText('Delete this group?')).toBeInTheDocument()
    })

    it('removes a group from view without touching the server', async () => {
      const { user } = renderDialog({ importReview: { groupIds: [1, 2, 3] } })
      await screen.findByText('3 groups')
      const row = sidebarRow('Town Maps').closest('.group\\/navrow') as HTMLElement
      await user.click(within(row).getAllByRole('button')[1])
      await user.click(screen.getByRole('menuitem', { name: /Remove from view/ }))
      expect(await screen.findByText('2 groups')).toBeInTheDocument()
      expect(groupApi.delete).not.toHaveBeenCalled()
    })

    it('bulk merges and deletes ctrl-selected groups', async () => {
      const { user } = renderDialog({ importReview: { groupIds: [1, 2, 3] } })
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
  describe('large import review', () => {
    beforeEach(() => {
      // 3,000 images a group by their summaries: over LARGE_REVIEW_IMAGES in all
      vi.mocked(groupApi.summaries).mockImplementation(async (ids) =>
        ids.map((id) => ({ ...summaryOf(GROUPS[id]), image_count: 3000 })),
      )
      vi.mocked(imageApi.facets).mockResolvedValue({
        total: 9000,
        image_type: [{ value: 'battlemap', count: 9000 }],
        grid: [
          { value: 'square', count: 0 },
          { value: 'gridless', count: 400 },
          { value: 'unknown', count: 8600 },
        ],
        subgroup: [{ value: null, count: 9000 }],
        tags: [],
      })
      vi.mocked(imageApi.bulkEdit).mockResolvedValue({ updated: 400, undo_id: 'u' })
    })

    it('loads only the group it opens on, and others when they are opened', async () => {
      const { user } = renderDialog({ importReview: { groupIds: [1, 2, 3] } })
      expect(await screen.findByDisplayValue('Forest Maps')).toBeInTheDocument()
      expect(groupApi.details).toHaveBeenCalledTimes(1)
      expect(groupApi.details).toHaveBeenCalledWith([1])

      await user.click(screen.getByRole('button', { name: /Town Maps/ }))
      expect(await screen.findByDisplayValue('Town Maps')).toBeInTheDocument()
      expect(groupApi.details).toHaveBeenLastCalledWith([3])
      // Cave Maps was never opened, so never fetched
      expect(groupApi.details).toHaveBeenCalledTimes(2)
    })

    it('renders only the sidebar rows on screen for thousands of groups', async () => {
      const ids = Array.from({ length: 2000 }, (_, i) => i + 1)
      const named = (id: number) => ({ ...summaryOf(GROUPS[1]), id, base_name: `Pack ${id}` })
      vi.mocked(groupApi.summaries).mockImplementation(async (asked) => asked.map(named))
      vi.mocked(groupApi.details).mockImplementation(async (asked) =>
        asked.map((id) => ({ ...structuredClone(GROUPS[1]), id, base_name: `Pack ${id}` })),
      )
      const restoreLayout = fakeLayout({ width: 800, height: 600 })
      try {
        renderDialog({ importReview: { groupIds: ids } })
        expect(await screen.findByText('2,000 groups')).toBeInTheDocument()
        const rows = screen.getAllByRole('button', { name: /^Pack \d+/ })
        expect(rows.length).toBeGreaterThan(0)
        expect(rows.length).toBeLessThan(100)
        expect(screen.queryByRole('button', { name: /^Pack 2000/ })).not.toBeInTheDocument()
      } finally {
        restoreLayout()
      }
    })

    it('shows All as a panel of counts whose edits go by scope', async () => {
      const { user } = renderDialog({ importReview: { groupIds: [1, 2, 3] } })
      await screen.findByDisplayValue('Forest Maps')
      await user.click(screen.getByRole('button', { name: /^All\s*[\d,]+$/ }))

      expect(await screen.findByText('9,000 images in 3 groups')).toBeInTheDocument()
      await user.click(screen.getByRole('button', { name: /^Gridless/ }))
      expect(screen.getByText(/Change the 400 Gridless images/)).toBeInTheDocument()
      await user.click(screen.getByRole('button', { name: /^Type/ }))
      await user.click(await screen.findByRole('menuitem', { name: 'Scene' }))

      await waitFor(() =>
        expect(imageApi.bulkEdit).toHaveBeenCalledWith(
          { scope: { group_ids: [1, 2, 3], filter: { grid: 'gridless' } } },
          { image_type: 'scene' },
          [],
        ),
      )
    })
  })

  describe('images Auto skipped', () => {
    let manager: ImportManager
    const skippedFrom = (importGroupId: number, id: number) =>
      item({
        id,
        import_group_id: importGroupId,
        filename: `token_${id}.png`,
        state: 'skipped',
        error_kind: 'sorted_out',
        error_reason: 'Looks like a token',
      })

    beforeEach(async () => {
      // Import groups 1 and 2 went into gallery groups 1 (Forest Maps) and 2 (Cave Maps)
      ;({ manager } = await installFakeImportManager({
        items: [skippedFrom(1, 50), skippedFrom(1, 51), skippedFrom(2, 52)],
        importGroups: { 1: 1, 2: 2 },
      }))
    })
    afterEach(() => uninstallFakeImportManager(manager))

    it('offers them above a saved group', async () => {
      renderDialog({ groupId: 1 })
      expect(
        await screen.findByText('2 images from this group were skipped by Auto'),
      ).toBeInTheDocument()
    })

    it('counts them on sidebar rows, and offers them only for the one group open', async () => {
      const { user } = renderDialog({ importReview: { groupIds: [1, 2] } })
      expect(await screen.findByText('2 groups')).toBeInTheDocument()
      // A long name is cut off on the row; hovering shows it in full
      expect(screen.getByTitle('Cave Maps')).toHaveTextContent('Cave Maps')
      // Each row reads as counts per kind: maps, scenes, skipped by Auto
      expect(await screen.findByTitle(/, 2 skipped by Auto$/)).toBeInTheDocument()
      expect(screen.getByTitle(/, 1 skipped by Auto$/)).toBeInTheDocument()
      // All shows several groups: no strip
      expect(screen.queryByText(/from this group/)).not.toBeInTheDocument()

      await user.click(sidebarRow('Cave Maps'))
      expect(screen.getByText('1 image from this group was skipped by Auto')).toBeInTheDocument()

      // Several groups picked at once: no strip either
      await user.keyboard('{Control>}')
      await user.click(sidebarRow('Cave Maps'))
      await user.click(sidebarRow('Forest Maps'))
      await user.keyboard('{/Control}')
      expect(screen.getByText('2 selected')).toBeInTheDocument()
      expect(screen.queryByText(/from this group/)).not.toBeInTheDocument()
    })
  })

  describe('author and name', () => {
    it('saves nothing when the fields lose focus unchanged', async () => {
      const { user } = renderDialog({ importReview: { groupIds: [1, 3] } })
      await screen.findByText('2 groups')
      await user.click(screen.getByPlaceholderText(/Multiple/))
      await user.tab()
      expect(groupApi.edit).not.toHaveBeenCalled()
      expect(groupApi.bulkUpdate).not.toHaveBeenCalled()
    })

    it('sets the author of every group in one request', async () => {
      const { user } = renderDialog({ importReview: { groupIds: [1, 3] } })
      await screen.findByText('2 groups')
      await user.type(screen.getByPlaceholderText(/Multiple/), 'Mapmaker')
      await user.tab()
      await waitFor(() => expect(groupApi.bulkUpdate).toHaveBeenCalledTimes(1))
      expect(groupApi.bulkUpdate).toHaveBeenCalledWith([1, 3], 'Mapmaker')
      expect(groupApi.edit).not.toHaveBeenCalled()
    })

    it('saves a renamed group on its own', async () => {
      const { user } = renderDialog({ groupId: 1 })
      const name = await screen.findByDisplayValue('Forest Maps')
      await user.type(name, ' II')
      await user.tab()
      await waitFor(() =>
        expect(groupApi.edit).toHaveBeenCalledWith(
          1,
          expect.objectContaining({ base_name: 'Forest Maps II' }),
        ),
      )
      expect(groupApi.bulkUpdate).not.toHaveBeenCalled()
    })
  })

  describe('bulk actions', () => {
    /** Select every file on the All tab, then pick Type → Scene from the toolbar. */
    async function setTypeOfAll(user: ReturnType<typeof userEvent.setup>) {
      await screen.findByText('2 groups')
      const toolbar = screen.getByText(/^\d+ files$/).parentElement!
      await user.click(within(toolbar).getByRole('checkbox'))
      await user.click(screen.getByRole('button', { name: /^Type/ }))
      await user.click(await screen.findByRole('menuitem', { name: 'Scene' }))
    }

    const responseFor = (target: { image_ids: number[] } | { scope: unknown }) => ({
      updated: 'image_ids' in target ? target.image_ids.length : 0,
      undo_id: 'undo-1',
    })

    it('saves in one bulk request, not by re-saving each group, and can be undone', async () => {
      vi.mocked(imageApi.bulkEdit).mockImplementation(async (ids) => responseFor(ids))
      const { user } = renderDialog({ importReview: { groupIds: [1, 2] } })
      await setTypeOfAll(user)

      await waitFor(() =>
        expect(imageApi.bulkEdit).toHaveBeenCalledWith(
          { image_ids: [11, 12, 13, 21] },
          { image_type: 'scene' },
          [],
        ),
      )
      expect(groupApi.edit).not.toHaveBeenCalled()
      expect(
        within(dialog()).getAllByRole('button', { name: 'Scene', pressed: true }),
      ).toHaveLength(4)

      const [message, options] = vi.mocked(toast.success).mock.lastCall!
      expect(message).toBe('Set type to scene: 4 images')
      const action = (options as unknown as { action: { onClick: () => void } }).action
      action.onClick()
      await waitFor(() => expect(imageApi.bulkRestore).toHaveBeenCalledWith('undo-1'))
      await waitFor(() =>
        expect(
          within(dialog()).queryAllByRole('button', { name: 'Scene', pressed: true }),
        ).toHaveLength(0),
      )
    })

    it('asks before editing 500 images or more', async () => {
      const big: GroupDetail = {
        id: 5,
        base_name: 'Huge Pack',
        author: null,
        primary_image_id: 1000,
        images: Array.from({ length: 499 }, (_, i) => makeImage(1000 + i, { group_id: 5 })),
      }
      const all: Record<number, GroupDetail> = { ...GROUPS, 5: big }
      vi.mocked(groupApi.summaries).mockImplementation(async (ids) =>
        ids.map((id) => summaryOf(all[id])),
      )
      vi.mocked(groupApi.details).mockImplementation(async (ids) =>
        ids.map((id) => structuredClone(all[id])),
      )
      vi.mocked(imageApi.bulkEdit).mockImplementation(async (ids) => responseFor(ids))
      const { user } = renderDialog({ importReview: { groupIds: [2, 5] } })
      await setTypeOfAll(user)

      const confirm = await screen.findByRole('dialog', { name: 'Edit many images?' })
      expect(confirm).toHaveTextContent('Set type to scene on 500 images?')
      expect(imageApi.bulkEdit).not.toHaveBeenCalled()
      await user.click(within(confirm).getByRole('button', { name: 'Apply' }))
      await waitFor(() => expect(imageApi.bulkEdit).toHaveBeenCalledTimes(1))
      expect(vi.mocked(imageApi.bulkEdit).mock.calls[0][0]).toEqual({
        image_ids: expect.any(Array),
      })
      expect(vi.mocked(toast.success).mock.lastCall![0]).toBe('Set type to scene: 500 images')
    })

    it('puts the files back when the request fails', async () => {
      vi.mocked(imageApi.bulkEdit).mockRejectedValue(new Error('Database is locked'))
      const { user } = renderDialog({ importReview: { groupIds: [1, 2] } })
      await setTypeOfAll(user)

      await waitFor(() => expect(toast.error).toHaveBeenCalled())
      expect(
        within(dialog()).queryAllByRole('button', { name: 'Scene', pressed: true }),
      ).toHaveLength(0)
    })
  })
})
