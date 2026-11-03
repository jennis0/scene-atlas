import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test/renderWithProviders'
import { libraryApi } from '@/lib/api/libraryApi'
import { jobApi } from '@/lib/api'
import type { BackgroundJob } from '@/types'
import { FullExportRow } from './FullExportRow'

const mode = vi.hoisted(() => ({ isApp: false }))
vi.mock('@/lib/appMode', () => ({
  get isApp() {
    return mode.isApp
  },
}))
vi.mock('@/lib/api/libraryApi', () => ({
  libraryApi: { startFullExport: vi.fn(), fullExportStatus: vi.fn(), status: vi.fn() },
}))
vi.mock('@/hooks/useLibraryStatus', () => ({
  useLibraryStatus: () => ({
    data: linked.value ? { linked: { path: '/maps' } } : { linked: null },
  }),
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
const linked = vi.hoisted(() => ({ value: false }))

function job(over: Partial<BackgroundJob>): BackgroundJob {
  return {
    id: 'job-1',
    name: 'Exporting library',
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

const SERVER_DIR = '/srv/images/exports'

describe('FullExportRow', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mode.isApp = false
    linked.value = false
    vi.mocked(libraryApi.startFullExport).mockResolvedValue({ job_id: 'job-1', path: '/x' })
    vi.mocked(libraryApi.fullExportStatus).mockResolvedValue({
      job_id: null,
      folder: SERVER_DIR,
      latest: null,
    })
  })
  afterEach(() => {
    delete window.electronAPI
  })

  it('on a server, says where it writes and reports what it exported', async () => {
    vi.spyOn(jobApi, 'get').mockResolvedValue(
      job({
        result: { path: `${SERVER_DIR}/a`, images: 1200, skipped: 1, problems: ['x.png: gone'] },
      }),
    )
    const user = userEvent.setup()
    renderWithProviders(<FullExportRow />)
    expect(await screen.findByText(SERVER_DIR)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Export library' }))

    expect(libraryApi.startFullExport).toHaveBeenCalledWith({
      path: undefined,
      resume: false,
      includeLinked: true,
    })
    expect(await screen.findByText(/Exported 1,200 images/)).toBeInTheDocument()
    expect(screen.getByText("1 couldn't be exported")).toBeInTheDocument()
    expect(screen.getByText('x.png: gone')).toBeInTheDocument()
  })

  it('carries on an export that stopped', async () => {
    vi.spyOn(jobApi, 'get').mockResolvedValue(
      job({ status: 'failed', error: 'Not enough space: 3.0 GB to write, 1.0 GB free' }),
    )
    const user = userEvent.setup()
    renderWithProviders(<FullExportRow />)
    await user.click(screen.getByRole('button', { name: 'Export library' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Not enough space')

    await user.click(screen.getByRole('button', { name: 'Carry on' }))
    expect(libraryApi.startFullExport).toHaveBeenLastCalledWith(
      expect.objectContaining({ resume: true }),
    )
  })

  it('in the desktop app, exports into the folder picked, and carries on there', async () => {
    mode.isApp = true
    const chooseExportFolder = vi.fn(async () => '/home/me/Export')
    window.electronAPI = { chooseExportFolder } as unknown as Window['electronAPI']
    vi.mocked(libraryApi.startFullExport).mockResolvedValue({
      job_id: 'job-1',
      path: '/home/me/Export',
    })
    vi.spyOn(jobApi, 'get').mockResolvedValue(job({ status: 'failed', error: 'disk' }))
    const user = userEvent.setup()
    renderWithProviders(<FullExportRow />)
    await user.click(screen.getByRole('button', { name: 'Export library…' }))
    expect(libraryApi.startFullExport).toHaveBeenCalledWith({
      path: '/home/me/Export',
      resume: false,
      includeLinked: true,
    })
    await user.click(await screen.findByRole('button', { name: 'Carry on' }))
    expect(chooseExportFolder).toHaveBeenCalledTimes(1) // not asked again
    expect(libraryApi.startFullExport).toHaveBeenLastCalledWith(
      expect.objectContaining({ path: '/home/me/Export', resume: true }),
    )
  })

  it('does nothing when the folder picker is cancelled', async () => {
    mode.isApp = true
    window.electronAPI = {
      chooseExportFolder: vi.fn(async () => null),
    } as unknown as Window['electronAPI']
    const user = userEvent.setup()
    renderWithProviders(<FullExportRow />)
    await user.click(screen.getByRole('button', { name: 'Export library…' }))
    await waitFor(() => expect(libraryApi.startFullExport).not.toHaveBeenCalled())
  })

  it('can leave the linked library out', async () => {
    linked.value = true
    const user = userEvent.setup()
    renderWithProviders(<FullExportRow />)
    await user.click(screen.getByRole('checkbox'))
    await user.click(screen.getByRole('button', { name: 'Export library' }))
    expect(libraryApi.startFullExport).toHaveBeenCalledWith(
      expect.objectContaining({ includeLinked: false }),
    )
  })
})
