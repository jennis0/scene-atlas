import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test/renderWithProviders'
import { libraryApi, type RebuildCheck, type RebuildStatus } from '@/lib/api/libraryApi'
import { jobApi } from '@/lib/api'
import type { BackgroundJob } from '@/types'
import { RebuildRow } from './RebuildRow'

vi.mock('@/lib/api/libraryApi', () => ({
  libraryApi: {
    rebuildStatus: vi.fn(),
    uploadRebuild: vi.fn(),
    checkRebuild: vi.fn(),
    buildRebuild: vi.fn(),
    applyRebuild: vi.fn(),
    cancelRebuild: vi.fn(),
    dismissRebuildSummary: vi.fn(),
  },
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }))

const EMPTY: RebuildStatus = {
  staged: false,
  check: null,
  check_error: null,
  built: false,
  job_id: null,
  summary: null,
  set_aside_running: false,
}

const CHECK: RebuildCheck = {
  images: 120,
  groups: 30,
  created_at: '2026-11-01T10:00:00+00:00',
  app_version: '0.2.0',
  different_library: false,
  reembed: false,
  linked_checked: true,
  missing: {
    images: 7,
    group_count: 3,
    groups: [{ name: 'Czepeku – Golden Forest', images: ['Day', 'Night'] }],
  },
  lost: { images: 3, group_count: 1, groups: [{ name: 'Tom – Harbour', images: ['A', 'B', 'C'] }] },
  missing_stored: 7,
  linked_missing: 0,
  linked_lost: 2,
}

function job(over: Partial<BackgroundJob>): BackgroundJob {
  return {
    id: 'job-1',
    name: 'Checking the export',
    status: 'completed',
    submitted_at: '',
    started_at: null,
    finished_at: null,
    progress: null,
    progress_pct: null,
    result: null,
    error: null,
    ...over,
  }
}

describe('RebuildRow', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(libraryApi.rebuildStatus).mockResolvedValue(EMPTY)
    vi.mocked(libraryApi.checkRebuild).mockResolvedValue({ job_id: 'job-1' })
    vi.mocked(libraryApi.buildRebuild).mockResolvedValue({ job_id: 'job-2' })
    vi.spyOn(jobApi, 'get').mockResolvedValue(job({}))
  })
  afterEach(() => {
    delete window.electronAPI
  })

  it('uploads the chosen export and checks it', async () => {
    const user = userEvent.setup()
    renderWithProviders(<RebuildRow />)
    const file = new File(['{}'], 'scene-atlas-metadata.jsonl.gz')
    vi.mocked(libraryApi.rebuildStatus).mockResolvedValue({ ...EMPTY, staged: true, check: CHECK })
    await user.upload(screen.getByLabelText('Metadata export to rebuild from'), file)
    expect(libraryApi.uploadRebuild).toHaveBeenCalledWith(file, expect.any(Function))
    expect(libraryApi.checkRebuild).toHaveBeenCalled()
    expect(await screen.findByText('7 images in 3 groups are missing.')).toBeInTheDocument()
  })

  it('says what is missing and what will be lost, group by group', async () => {
    vi.mocked(libraryApi.rebuildStatus).mockResolvedValue({ ...EMPTY, staged: true, check: CHECK })
    renderWithProviders(<RebuildRow />)
    expect(
      await screen.findByText('3 images in 1 group in your current library will be lost.'),
    ).toBeInTheDocument()
    expect(screen.getByText('Czepeku – Golden Forest (2)')).toBeInTheDocument()
    expect(screen.getByText('Night')).toBeInTheDocument()
  })

  it('warns about an export from another library', async () => {
    vi.mocked(libraryApi.rebuildStatus).mockResolvedValue({
      ...EMPTY,
      staged: true,
      check: { ...CHECK, different_library: true, reembed: true },
    })
    renderWithProviders(<RebuildRow />)
    expect(await screen.findByText('This export is from a different library.')).toBeInTheDocument()
    expect(screen.getByText(/processed again/)).toBeInTheDocument()
  })

  it('rebuilds, then restarts the desktop app into it', async () => {
    vi.mocked(libraryApi.rebuildStatus).mockResolvedValue({ ...EMPTY, staged: true, check: CHECK })
    vi.mocked(libraryApi.applyRebuild).mockResolvedValue({ restart: 'app' })
    const restartBackend = vi.fn(async () => false)
    window.electronAPI = { restartBackend } as unknown as Window['electronAPI']
    const user = userEvent.setup()
    renderWithProviders(<RebuildRow />)
    vi.mocked(libraryApi.rebuildStatus).mockResolvedValue({ ...EMPTY, built: true })
    await user.click(await screen.findByRole('button', { name: 'Rebuild' }))
    expect(libraryApi.buildRebuild).toHaveBeenCalled()

    await user.click(await screen.findByRole('button', { name: 'Restart now' }))
    expect(libraryApi.applyRebuild).toHaveBeenCalled()
    await waitFor(() => expect(restartBackend).toHaveBeenCalled())
    expect(
      await screen.findByText('Restart Scene Atlas to finish the rebuild.'),
    ).toBeInTheDocument()
  })

  it('cancel forgets the export', async () => {
    vi.mocked(libraryApi.rebuildStatus).mockResolvedValue({ ...EMPTY, staged: true, check: CHECK })
    const user = userEvent.setup()
    renderWithProviders(<RebuildRow />)
    await user.click(await screen.findByRole('button', { name: 'Cancel' }))
    expect(libraryApi.cancelRebuild).toHaveBeenCalled()
  })

  it('says a failed check changed nothing', async () => {
    vi.mocked(libraryApi.rebuildStatus).mockResolvedValue({ ...EMPTY, job_id: 'job-1' })
    vi.spyOn(jobApi, 'get').mockResolvedValue(
      job({ status: 'failed', error: "The file can't be read: Line 3: not valid JSON." }),
    )
    renderWithProviders(<RebuildRow />)
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Nothing in your library has changed',
    )
  })

  it('reports files set aside after a rebuild', async () => {
    vi.mocked(libraryApi.rebuildStatus).mockResolvedValue({
      ...EMPTY,
      summary: { id: 'x', moved: 3, folder: '/lib/not-in-backup/x' },
    })
    renderWithProviders(<RebuildRow />)
    expect(await screen.findByText(/3 files the export didn't have are in/)).toBeInTheDocument()
  })
  it('shows why the last check failed when Settings is reopened', async () => {
    vi.mocked(libraryApi.rebuildStatus).mockResolvedValue({
      ...EMPTY,
      staged: true,
      check_error: "The file can't be read: Line 3: not valid JSON.",
    })
    const user = userEvent.setup()
    renderWithProviders(<RebuildRow />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Line 3')
    await user.click(screen.getByRole('button', { name: 'Forget that export' }))
    expect(libraryApi.cancelRebuild).toHaveBeenCalled()
  })

  it('says linked images not in the export come back from the linked library', async () => {
    vi.mocked(libraryApi.rebuildStatus).mockResolvedValue({ ...EMPTY, staged: true, check: CHECK })
    renderWithProviders(<RebuildRow />)
    expect(await screen.findByText(/2 linked images in your library/)).toBeInTheDocument()
  })
})
