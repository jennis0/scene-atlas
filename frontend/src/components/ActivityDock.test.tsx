import { afterEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test/renderWithProviders'
import {
  counts,
  idleQueue,
  installFakeImportManager,
  jobSummary,
  uninstallFakeImportManager,
} from '@/test/importFakes'
import type { ImportManager } from '@/lib/import/ImportManager'
import type { BackgroundJob } from '@/types'
import { ActivityDock } from './ActivityDock'

const runningBgJob: BackgroundJob = {
  id: 'bg-1',
  name: 'Regenerate Auto-Tags',
  status: 'running',
  submitted_at: new Date().toISOString(),
  started_at: new Date().toISOString(),
  finished_at: null,
  progress: 'Processing tags...',
  progress_pct: 47,
  result: null,
  error: null,
}

let manager: ImportManager | undefined
afterEach(() => {
  if (manager) uninstallFakeImportManager(manager)
  manager = undefined
})

describe('ActivityDock', () => {
  it('renders nothing when there are no imports or jobs', async () => {
    ;({ manager } = await installFakeImportManager())
    const { container } = renderWithProviders(
      <ActivityDock backgroundJobs={[]} onOpenImport={vi.fn()} />,
    )
    expect(container.firstChild).toBeNull()
  })

  it('counts running imports and background jobs on the pill', async () => {
    ;({ manager } = await installFakeImportManager({
      jobs: [
        jobSummary({ counts: counts({ ready: 2, done: 1 }) }),
        jobSummary({ id: 'j2', status: 'completed' }),
      ],
    }))
    renderWithProviders(<ActivityDock backgroundJobs={[runningBgJob]} onOpenImport={vi.fn()} />)
    expect(screen.getByTestId('activity-dock-pill')).toHaveTextContent('2')
  })

  it('lists imports with a status line and opens them', async () => {
    ;({ manager } = await installFakeImportManager({
      jobs: [jobSummary({ counts: counts({ processing: 2, done: 3 }) })],
    }))
    const onOpenImport = vi.fn()
    renderWithProviders(<ActivityDock backgroundJobs={[]} onOpenImport={onOpenImport} />)
    await userEvent.click(screen.getByTestId('activity-dock-pill'))
    const row = screen.getByTestId('import-job-card')
    expect(row).toHaveTextContent('Forest Pack')
    expect(row).toHaveTextContent('3 of 5 files processed')
    await userEvent.click(screen.getByText('Forest Pack'))
    expect(onOpenImport).toHaveBeenCalledWith('job1')
  })

  it('dismisses a finished import without asking', async () => {
    let client
    ;({ manager, client } = await installFakeImportManager({
      jobs: [jobSummary({ status: 'completed', counts: counts({ done: 4, failed: 1 }) })],
    }))
    renderWithProviders(<ActivityDock backgroundJobs={[]} onOpenImport={vi.fn()} />)
    await userEvent.click(screen.getByTestId('activity-dock-pill'))
    expect(screen.getByTestId('import-job-card')).toHaveTextContent('4 imported, 1 failed')
    await userEvent.click(screen.getByTitle('Dismiss'))
    expect(client!.action).toHaveBeenCalledWith('job1', 'dismiss')
  })

  it('pauses a running import from its row', async () => {
    let client
    ;({ manager, client } = await installFakeImportManager({
      jobs: [jobSummary({ counts: counts({ ready: 1 }) })],
    }))
    renderWithProviders(<ActivityDock backgroundJobs={[]} onOpenImport={vi.fn()} />)
    await userEvent.click(screen.getByTestId('activity-dock-pill'))
    await userEvent.click(screen.getByTitle('Pause'))
    expect(client!.action).toHaveBeenCalledWith('job1', 'pause')
  })

  it('explains a system pause and retries on request', async () => {
    let client
    ;({ manager, client } = await installFakeImportManager({
      jobs: [jobSummary({ counts: counts({ ready: 1 }) })],
      queue: {
        ...idleQueue,
        system_paused: true,
        reason: 'Not enough free disk space on the image library drive',
      },
    }))
    renderWithProviders(<ActivityDock backgroundJobs={[]} onOpenImport={vi.fn()} />)
    await userEvent.click(screen.getByTestId('activity-dock-pill'))
    expect(screen.getByText(/Not enough free disk space/)).toBeInTheDocument()
    await userEvent.click(screen.getByText('Try again'))
    expect(client!.probeQueue).toHaveBeenCalled()
  })

  it('flags an interrupted upload', async () => {
    ;({ manager } = await installFakeImportManager({
      jobs: [
        jobSummary({ upload_interrupted: true, counts: counts({ awaiting_bytes: 7, done: 3 }) }),
      ],
    }))
    renderWithProviders(<ActivityDock backgroundJobs={[]} onOpenImport={vi.fn()} />)
    await userEvent.click(screen.getByTestId('activity-dock-pill'))
    expect(screen.getByTestId('import-job-card')).toHaveTextContent('Upload interrupted')
  })

  it('shows offline when the server is unreachable', async () => {
    let client
    ;({ manager, client } = await installFakeImportManager({ jobs: [jobSummary()] }))
    client!.list.mockRejectedValue(
      Object.assign(new Error('Network Error'), { code: 'ERR_NETWORK' }),
    )
    await manager.refresh()
    await manager.refresh()
    await manager.refresh()
    renderWithProviders(<ActivityDock backgroundJobs={[]} onOpenImport={vi.fn()} />)
    await waitFor(() => expect(screen.getByText('Offline')).toBeInTheDocument())
  })

  it('still shows background jobs', async () => {
    ;({ manager } = await installFakeImportManager())
    renderWithProviders(<ActivityDock backgroundJobs={[runningBgJob]} onOpenImport={vi.fn()} />)
    await userEvent.click(screen.getByTestId('activity-dock-pill'))
    expect(screen.getByText('Regenerate Auto-Tags')).toBeInTheDocument()
  })
})
