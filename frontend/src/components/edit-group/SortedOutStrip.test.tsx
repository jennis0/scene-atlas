import { afterEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test/renderWithProviders'
import {
  installFakeImportManager,
  item,
  uninstallFakeImportManager,
  type FakeImportClient,
} from '@/test/importFakes'
import type { ImportManager } from '@/lib/import/ImportManager'
import { SortedOutStrip } from './SortedOutStrip'

let manager: ImportManager | undefined
let client: FakeImportClient
afterEach(() => {
  if (manager) uninstallFakeImportManager(manager)
  manager = undefined
})

const skipped = (id: number, filename: string) =>
  item({
    id,
    job_id: 'job1',
    filename,
    relative_path: `P/${filename}`,
    state: 'skipped',
    error_kind: 'sorted_out',
    error_reason: 'Looks like a token',
    has_preview: true,
  })

describe('SortedOutStrip', () => {
  it('renders nothing when Auto skipped nothing from the group', async () => {
    ;({ manager, client } = await installFakeImportManager())
    const { container } = renderWithProviders(
      <SortedOutStrip groupId={41} count={0} onIncluded={() => {}} />,
    )
    expect(container).toBeEmptyDOMElement()
  })

  it('loads previews only when reviewed, and includes one or all', async () => {
    ;({ manager, client } = await installFakeImportManager({
      items: [skipped(20, 'goblin.png'), skipped(21, 'orc.png')],
    }))
    const onIncluded = vi.fn()
    renderWithProviders(<SortedOutStrip groupId={41} count={2} onIncluded={onIncluded} />)
    expect(screen.getByText('2 images from this group were skipped by Auto')).toBeInTheDocument()
    expect(client.sortedOut).not.toHaveBeenCalled()

    await userEvent.click(screen.getByRole('button', { name: 'Review' }))
    await waitFor(() => expect(screen.getByText('goblin.png')).toBeInTheDocument())
    expect(client.sortedOut).toHaveBeenCalledWith(41)

    await userEvent.click(screen.getAllByRole('button', { name: 'Include' })[0])
    expect(client.include).toHaveBeenCalledWith([20])
    await waitFor(() => expect(screen.queryByText('goblin.png')).not.toBeInTheDocument())
    expect(onIncluded).toHaveBeenCalled()
    expect(screen.getByText(/1 being imported/)).toBeInTheDocument()
    expect(screen.getByText('1 image from this group was skipped by Auto')).toBeInTheDocument()
  })

  it('includes them all at once', async () => {
    ;({ manager, client } = await installFakeImportManager({
      items: [skipped(20, 'goblin.png'), skipped(21, 'orc.png')],
    }))
    renderWithProviders(<SortedOutStrip groupId={41} count={2} onIncluded={() => {}} />)
    await userEvent.click(screen.getByRole('button', { name: 'Review' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Include all' }))
    expect(client.include).toHaveBeenCalledWith([20, 21])
    await waitFor(() => expect(screen.getByText('No skipped images left')).toBeInTheDocument())
  })
})
