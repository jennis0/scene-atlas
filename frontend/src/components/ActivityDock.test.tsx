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
  backgroundJobs: [] as BackgroundJob[],
  hasActiveJobs: false,
  onOpenJob: vi.fn(),
  onDismissJob: vi.fn(),
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
})
