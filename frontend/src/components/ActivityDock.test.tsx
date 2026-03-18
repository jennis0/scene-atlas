import { describe, it, expect, vi } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test/renderWithProviders'
import { ActivityDock } from './ActivityDock'
import type { ActiveImportJob } from '@/hooks/useActiveImports'
import type { BackgroundJob } from '@/types'

vi.mock('@/lib/api', () => ({
  importApi: { cleanup: vi.fn().mockResolvedValue(undefined) },
}))

const baseProps = {
  jobs: [] as ActiveImportJob[],
  hasActive: false,
  connectionLost: false,
  backgroundJobs: [] as BackgroundJob[],
  hasActiveJobs: false,
  onOpenJob: vi.fn(),
  onDismissJob: vi.fn(),
  onDismissWithCleanup: vi.fn().mockResolvedValue(undefined),
  onCancelJob: vi.fn(),
  onRefresh: vi.fn(),
}

const runningImport: ActiveImportJob = {
  jobId: 'imp-1',
  label: 'Dark Forest Maps',
  status: 'running',
  totalGroups: 8,
  completedGroups: 3,
  failedGroups: 0,
  runningGroups: 2,
  pendingGroups: 3,
  totalFiles: 24,
  processedFiles: 9,
  createdAt: new Date().toISOString(),
  localOnly: false,
  failedFiles: 0,
  warningCount: 0,
}

const completedImport: ActiveImportJob = {
  ...runningImport,
  jobId: 'imp-2',
  label: 'Coastal Ruins',
  status: 'completed',
  completedGroups: 4,
  totalGroups: 4,
  runningGroups: 0,
  pendingGroups: 0,
}

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

describe('ActivityDock', () => {
  it('renders nothing when no jobs exist', () => {
    const { container } = renderWithProviders(<ActivityDock {...baseProps} />)
    expect(container.firstChild).toBeNull()
  })

  it('shows pill with Activity text when jobs exist', () => {
    renderWithProviders(<ActivityDock {...baseProps} jobs={[runningImport]} hasActive />)
    expect(screen.getByText('Activity')).toBeInTheDocument()
  })

  it('shows active count badge on pill', () => {
    renderWithProviders(
      <ActivityDock
        {...baseProps}
        jobs={[runningImport]}
        hasActive
        backgroundJobs={[runningBgJob]}
        hasActiveJobs
      />,
    )
    // 1 running import + 1 running background = 2
    expect(screen.getByText('2')).toBeInTheDocument()
  })

  it('hides badge when only terminal jobs exist', () => {
    renderWithProviders(<ActivityDock {...baseProps} jobs={[completedImport]} />)
    expect(screen.getByText('Activity')).toBeInTheDocument()
    expect(screen.queryByText('1')).not.toBeInTheDocument()
  })

  it('expands on pill click to show card', async () => {
    const user = userEvent.setup()
    renderWithProviders(<ActivityDock {...baseProps} jobs={[runningImport]} hasActive />)
    await user.click(screen.getByText('Activity'))
    expect(screen.getByText('Dark Forest Maps')).toBeInTheDocument()
  })

  it('shows background job names in expanded card', async () => {
    const user = userEvent.setup()
    renderWithProviders(
      <ActivityDock {...baseProps} backgroundJobs={[runningBgJob]} hasActiveJobs />,
    )
    await user.click(screen.getByText('Activity'))
    expect(screen.getByText('Regenerate Auto-Tags')).toBeInTheDocument()
  })

  it('calls onOpenJob when clicking import card', async () => {
    const onOpenJob = vi.fn()
    const user = userEvent.setup()
    renderWithProviders(
      <ActivityDock {...baseProps} jobs={[runningImport]} hasActive onOpenJob={onOpenJob} />,
    )
    await user.click(screen.getByText('Activity'))
    await user.click(screen.getByText('Dark Forest Maps'))
    expect(onOpenJob).toHaveBeenCalledWith('imp-1')
  })

  it('shows Offline label on collapsed pill when connectionLost', () => {
    renderWithProviders(
      <ActivityDock {...baseProps} jobs={[runningImport]} hasActive connectionLost />,
    )
    expect(screen.getByText('Offline')).toBeInTheDocument()
  })

  it('shows Connection lost indicator in expanded header when connectionLost', async () => {
    const user = userEvent.setup()
    renderWithProviders(
      <ActivityDock {...baseProps} jobs={[runningImport]} hasActive connectionLost />,
    )
    await user.click(screen.getByText('Activity'))
    expect(screen.getByText('Connection lost')).toBeInTheDocument()
  })

  it('shows cancel button on running import jobs', async () => {
    const onCancelJob = vi.fn()
    const user = userEvent.setup()
    renderWithProviders(
      <ActivityDock {...baseProps} jobs={[runningImport]} hasActive onCancelJob={onCancelJob} />,
    )
    await user.click(screen.getByText('Activity'))
    // Hover the card to reveal the cancel button
    const card = screen.getByTestId('import-job-card')
    await user.hover(card)
    const cancelBtn = screen.getByTitle('Cancel')
    expect(cancelBtn).toBeInTheDocument()
  })

  it('shows dismiss button on broken import jobs', async () => {
    const brokenImport: ActiveImportJob = {
      ...runningImport,
      jobId: 'imp-broken',
      status: 'broken',
      runningGroups: 0,
      pendingGroups: 0,
      errorMessage: 'Server was restarted',
    }
    const onDismissWithCleanup = vi.fn().mockResolvedValue(undefined)
    const user = userEvent.setup()
    renderWithProviders(
      <ActivityDock
        {...baseProps}
        jobs={[brokenImport]}
        onDismissWithCleanup={onDismissWithCleanup}
      />,
    )
    await user.click(screen.getByText('Activity'))
    const card = screen.getByTestId('import-job-card')
    await user.hover(card)
    const dismissBtn = screen.getByTitle('Dismiss')
    expect(dismissBtn).toBeInTheDocument()
  })
})
