import { afterEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test/renderWithProviders'
import {
  installFakeImportManager,
  item,
  jobSummary,
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
    filename,
    relative_path: `P/${filename}`,
    state: 'skipped',
    error_kind: 'sorted_out',
    error_reason: 'Looks like a token',
    has_preview: true,
  })

const finished = jobSummary({ status: 'completed' })

describe('SortedOutStrip', () => {
  it('renders nothing when Auto skipped nothing from the group', async () => {
    ;({ manager, client } = await installFakeImportManager())
    const { container } = renderWithProviders(
      <SortedOutStrip groupId={41} count={0} importing={0} onIncluded={() => {}} />,
    )
    expect(container).toBeEmptyDOMElement()
  })

  it('loads previews only when reviewed, and includes one or all', async () => {
    ;({ manager, client } = await installFakeImportManager({
      jobs: [finished],
      items: [skipped(20, 'goblin.png'), skipped(21, 'orc.png')],
    }))
    const onIncluded = vi.fn()
    const { rerender } = renderWithProviders(
      <SortedOutStrip groupId={41} count={2} importing={0} onIncluded={onIncluded} />,
    )
    expect(screen.getByText('2 images from this group were skipped by Auto')).toBeInTheDocument()
    expect(client.sortedOut).not.toHaveBeenCalled()

    await userEvent.click(screen.getByRole('button', { name: 'Review' }))
    await waitFor(() => expect(screen.getByText('goblin.png')).toBeInTheDocument())
    expect(client.sortedOut).toHaveBeenCalledWith(41)

    await userEvent.click(screen.getByRole('button', { name: 'Include goblin.png' }))
    expect(client.include).toHaveBeenCalledWith([20])
    await waitFor(() => expect(screen.queryByText('goblin.png')).not.toBeInTheDocument())
    expect(onIncluded).toHaveBeenCalledWith(1, ['job1'])
    // The dialog re-reads the count, tracks the import and passes back what's on its way
    rerender(<SortedOutStrip groupId={41} count={1} importing={1} onIncluded={onIncluded} />)
    expect(screen.getByText(/1 being imported/)).toBeInTheDocument()
    expect(screen.getByText('1 image from this group was skipped by Auto')).toBeInTheDocument()
  })

  it('includes them all at once', async () => {
    ;({ manager, client } = await installFakeImportManager({
      jobs: [finished],
      items: [skipped(20, 'goblin.png'), skipped(21, 'orc.png')],
    }))
    const { rerender } = renderWithProviders(
      <SortedOutStrip groupId={41} count={2} importing={0} onIncluded={() => {}} />,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Review' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Include all' }))
    expect(client.include).toHaveBeenCalledWith([20, 21])
    rerender(<SortedOutStrip groupId={41} count={0} importing={2} onIncluded={() => {}} />)
    expect(screen.getByText('No skipped images left')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Review' })).not.toBeInTheDocument()
  })

  it('counts from the server when the list is cut short, and reloads it after an include', async () => {
    const items = [1, 2, 3, 4, 5].map((n) => skipped(n, `token-${n}.png`))
    ;({ manager, client } = await installFakeImportManager({
      jobs: [finished],
      items,
      sortedOutLimit: 2,
    }))
    renderWithProviders(
      <SortedOutStrip groupId={41} count={5} importing={0} onIncluded={() => {}} />,
    )
    expect(screen.getByText('5 images from this group were skipped by Auto')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Review' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Include these 2' }))
    expect(client.include).toHaveBeenCalledWith([1, 2])
    // The next ones come in, and Review stays while the server still counts some
    await waitFor(() => expect(screen.getByText('token-3.png')).toBeInTheDocument())
    expect(client.sortedOut).toHaveBeenCalledTimes(2)
    expect(screen.getByRole('button', { name: 'Hide' })).toBeInTheDocument()
  })

  it('names its controls and keeps them out of the status announcement', async () => {
    ;({ manager, client } = await installFakeImportManager({
      jobs: [finished],
      items: [skipped(20, 'goblin.png')],
    }))
    renderWithProviders(
      <SortedOutStrip groupId={41} count={1} importing={0} onIncluded={() => {}} />,
    )
    const toggle = screen.getByRole('button', { name: 'Review' })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(within(screen.getByRole('status')).queryByRole('button')).not.toBeInTheDocument()

    await userEvent.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    const list = document.getElementById(toggle.getAttribute('aria-controls')!)
    expect(list).not.toBeNull()
    expect(
      await within(list!).findByRole('button', { name: 'Include goblin.png' }),
    ).toBeInTheDocument()
  })

  it('labels the loading spinner', async () => {
    ;({ manager, client } = await installFakeImportManager({ jobs: [finished] }))
    client.sortedOut.mockImplementationOnce(() => new Promise(() => {}))
    renderWithProviders(
      <SortedOutStrip groupId={41} count={1} importing={0} onIncluded={() => {}} />,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Review' }))
    expect(screen.getByRole('img', { name: 'Loading skipped images' })).toBeInTheDocument()
  })
})
