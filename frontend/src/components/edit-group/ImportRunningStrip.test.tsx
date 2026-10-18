import { afterEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test/renderWithProviders'
import {
  counts,
  group,
  installFakeImportManager,
  jobDetail,
  jobSummary,
  uninstallFakeImportManager,
} from '@/test/importFakes'
import type { ImportManager } from '@/lib/import/ImportManager'
import { ImportRunningStrip } from './ImportRunningStrip'

let manager: ImportManager | undefined
afterEach(() => {
  if (manager) uninstallFakeImportManager(manager)
  manager = undefined
})

const running = (partial = {}) =>
  jobSummary({
    counts: counts({ done: 6, ready: 40 }),
    group_count: 347,
    groups_done: 103,
    groups_reviewable: 3,
    ...partial,
  })

describe('ImportRunningStrip', () => {
  it('says the import is still running and goes back to its progress', async () => {
    ;({ manager } = await installFakeImportManager({ jobs: [running()] }))
    const onShowProgress = vi.fn()
    renderWithProviders(
      <ImportRunningStrip
        jobId="job1"
        reviewedGroupIds={[41, 42, 43]}
        onShowProgress={onShowProgress}
      />,
    )
    expect(screen.getByRole('status')).toHaveTextContent(
      'Import still running · 103 of 347 groups done',
    )
    expect(screen.queryByText(/more group/)).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Show progress' }))
    expect(onShowProgress).toHaveBeenCalled()
  })

  it('adds the groups finished since the editor opened, when asked', async () => {
    const groups = [41, 42, 43, 44, 45].map((id) => group({ id, image_group_id: id }))
    const reviewable = [41, 42, 43, 44, 45]
    ;({ manager } = await installFakeImportManager({
      jobs: [running({ groups_reviewable: 5 })],
      details: {
        job1: jobDetail({
          ...running({ groups_reviewable: 5 }),
          groups,
          reviewable_group_ids: reviewable,
        }),
      },
    }))
    const onAddGroups = vi.fn()
    renderWithProviders(
      <ImportRunningStrip jobId="job1" reviewedGroupIds={[41, 42, 43]} onAddGroups={onAddGroups} />,
    )
    expect(screen.getByText('2 more groups are ready')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Add them' }))
    await waitFor(() => expect(onAddGroups).toHaveBeenCalledWith([44, 45]))
  })

  it('reads the ready groups from the server, not from the import groups', async () => {
    // Group 46 is still filling; the server leaves it out
    const groups = [44, 45, 46].map((id) => group({ id, image_group_id: id }))
    ;({ manager } = await installFakeImportManager({
      jobs: [running({ groups_reviewable: 4 })],
      details: {
        job1: jobDetail({
          ...running({ groups_reviewable: 4 }),
          groups,
          reviewable_group_ids: [41, 42, 43, 45],
        }),
      },
    }))
    const onAddGroups = vi.fn()
    renderWithProviders(
      <ImportRunningStrip jobId="job1" reviewedGroupIds={[41, 42, 43]} onAddGroups={onAddGroups} />,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Add it' }))
    await waitFor(() => expect(onAddGroups).toHaveBeenCalledWith([45]))
    // Counted from that answer: nothing more until the summary moves on
    await waitFor(() => expect(screen.queryByText(/more group/)).not.toBeInTheDocument())
  })

  it('keeps its buttons out of the status announcement', async () => {
    ;({ manager } = await installFakeImportManager({ jobs: [running({ groups_reviewable: 5 })] }))
    renderWithProviders(
      <ImportRunningStrip
        jobId="job1"
        reviewedGroupIds={[41, 42, 43]}
        onAddGroups={vi.fn()}
        onShowProgress={vi.fn()}
      />,
    )
    expect(screen.getByRole('status').querySelector('button')).toBeNull()
  })

  it('stays until a finished import has nothing more to add', async () => {
    const done = running({ status: 'completed', groups_done: 347, groups_reviewable: 4 })
    ;({ manager } = await installFakeImportManager({ jobs: [done] }))
    const { rerender } = renderWithProviders(
      <ImportRunningStrip jobId="job1" reviewedGroupIds={[41, 42, 43]} onAddGroups={vi.fn()} />,
    )
    expect(screen.getByRole('status')).toHaveTextContent('Import finished · 347 groups')
    expect(screen.queryByRole('button', { name: 'Show progress' })).not.toBeInTheDocument()

    rerender(
      <ImportRunningStrip jobId="job1" reviewedGroupIds={[41, 42, 43, 44]} onAddGroups={vi.fn()} />,
    )
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })
})
