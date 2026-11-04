import { afterEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { toast } from 'sonner'
import { renderWithProviders } from '@/test/renderWithProviders'
import {
  installFakeImportManager,
  item,
  jobSummary,
  uninstallFakeImportManager,
  type FakeImportClient,
} from '@/test/importFakes'
import type { ImportManager } from '@/lib/import/ImportManager'
import { GroupSidebarShell } from '@/components/import/shared/GroupSidebarShell'
import { SkippedPanel } from './SkippedPanel'

let manager: ImportManager | undefined
let client: FakeImportClient
afterEach(() => {
  if (manager) uninstallFakeImportManager(manager)
  manager = undefined
})

/** Sorted out and in no group (import group 9 has no gallery group) */
const ungrouped = (id: number, filename: string, reason: string) =>
  item({
    id,
    filename,
    relative_path: `P/${filename}`,
    state: 'skipped',
    error_kind: 'sorted_out',
    error_reason: reason,
    has_preview: true,
    import_group_id: 9,
  })

const TOKEN = 'Looks like a token'
const ASSET = 'Looks like a map asset (a prop, overlay or tile)'

describe('SkippedPanel', () => {
  it("lists the import's skipped images in no group by reason, and includes one or all", async () => {
    const success = vi.spyOn(toast, 'success')
    ;({ manager, client } = await installFakeImportManager({
      jobs: [jobSummary({ status: 'completed', ungrouped_sorted_out: 3 })],
      items: [
        ungrouped(20, 'goblin.png', TOKEN),
        ungrouped(21, 'chest.png', ASSET),
        ungrouped(22, 'orc.png', TOKEN),
        // Sorted out from a gallery group: the group's own strip shows it
        item({ id: 23, state: 'skipped', error_kind: 'sorted_out', import_group_id: 1 }),
      ],
    }))
    renderWithProviders(<SkippedPanel jobId="job1" count={3} />)

    expect(screen.getByRole('heading', { name: 'Skipped by Auto' })).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText('goblin.png')).toBeInTheDocument())
    expect(client.sortedOutOfImport).toHaveBeenCalledWith('job1')
    const tokens = screen.getByRole('region', { name: TOKEN })
    expect(within(tokens).getAllByRole('listitem')).toHaveLength(2)
    expect(within(tokens).getByRole('heading')).toHaveTextContent(`${TOKEN} (2)`)
    // The reason heads the list, so tiles don't repeat it
    expect(within(tokens).queryByText(TOKEN, { selector: 'li *' })).toBeNull()
    expect(within(screen.getByRole('region', { name: ASSET })).getByText('chest.png'))

    await userEvent.click(screen.getByRole('button', { name: 'Include goblin.png' }))
    expect(client.include).toHaveBeenCalledWith([20])
    await waitFor(() =>
      expect(success).toHaveBeenCalledWith('Importing 1 image', {
        description: "They'll be grouped once imported.",
      }),
    )
    await waitFor(() => expect(screen.queryByText('goblin.png')).not.toBeInTheDocument())

    await userEvent.click(screen.getByRole('button', { name: 'Include all' }))
    expect(client.include).toHaveBeenLastCalledWith([21, 22])
    await waitFor(() => expect(screen.getByText('Nothing left to check.')).toBeInTheDocument())
    success.mockRestore()
  })
})

describe('GroupSidebarShell: Skipped row', () => {
  const allTab = { active: false, count: 4, onSelect: () => {} }

  it('lists the skipped images under the groups, and selects them', async () => {
    const onSelect = vi.fn()
    const { rerender } = renderWithProviders(
      <GroupSidebarShell
        headerLabel="2 groups"
        allTab={allTab}
        skippedTab={{ active: false, count: 3, onSelect }}
      >
        <div>Keep</div>
      </GroupSidebarShell>,
    )
    const row = screen.getByRole('button', { name: /Skipped by Auto/ })
    expect(row).toHaveTextContent('3')
    expect(row).not.toHaveAttribute('aria-current')
    await userEvent.click(row)
    expect(onSelect).toHaveBeenCalled()

    rerender(
      <GroupSidebarShell
        headerLabel="2 groups"
        allTab={allTab}
        skippedTab={{ active: true, count: 3, onSelect }}
      >
        <div>Keep</div>
      </GroupSidebarShell>,
    )
    expect(screen.getByRole('button', { name: /Skipped by Auto/ })).toHaveAttribute(
      'aria-current',
      'true',
    )
  })

  it('has no Skipped row without one', () => {
    renderWithProviders(
      <GroupSidebarShell headerLabel="2 groups" allTab={allTab}>
        <div>Keep</div>
      </GroupSidebarShell>,
    )
    expect(screen.queryByRole('button', { name: /Skipped by Auto/ })).not.toBeInTheDocument()
  })
})
