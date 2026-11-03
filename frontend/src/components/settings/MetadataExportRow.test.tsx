import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test/renderWithProviders'
import { libraryApi } from '@/lib/api/libraryApi'
import { jobApi } from '@/lib/api'
import { saveUrl } from '@/lib/download'
import type { BackgroundJob } from '@/types'
import { MetadataExportRow } from './MetadataExportRow'

vi.mock('@/lib/api/libraryApi', () => ({ libraryApi: { startMetadataExport: vi.fn() } }))
vi.mock('@/lib/download', () => ({ saveUrl: vi.fn() }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

function job(over: Partial<BackgroundJob>): BackgroundJob {
  return {
    id: 'job-1',
    name: 'Exporting metadata',
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

const NAME = 'scene-atlas-metadata-20261103-120000.jsonl.gz'

describe('MetadataExportRow', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(libraryApi.startMetadataExport).mockResolvedValue({ job_id: 'job-1' })
  })
  afterEach(() => {
    delete window.electronAPI
  })

  it('on a server, downloads the export once the job is done', async () => {
    vi.spyOn(jobApi, 'get').mockResolvedValue(
      job({ result: { name: NAME, path: `/data/exports/${NAME}` } }),
    )
    const user = userEvent.setup()
    renderWithProviders(<MetadataExportRow />)
    await user.click(screen.getByRole('button', { name: 'Export metadata' }))

    expect(libraryApi.startMetadataExport).toHaveBeenCalledWith(undefined)
    await waitFor(() =>
      expect(saveUrl).toHaveBeenCalledWith(`/api/v1/library/metadata-export/${NAME}`, NAME),
    )
    expect(saveUrl).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('link', { name: 'Download again' })).toBeInTheDocument()
  })

  it('in the desktop app, writes to the file the user picked', async () => {
    const chooseExportFile = vi.fn().mockResolvedValue('C:\\Backups\\mine.jsonl.gz')
    window.electronAPI = { chooseExportFile } as unknown as Window['electronAPI']
    vi.spyOn(jobApi, 'get').mockResolvedValue(
      job({ result: { name: 'mine.jsonl.gz', path: 'C:\\Backups\\mine.jsonl.gz' } }),
    )
    const user = userEvent.setup()
    renderWithProviders(<MetadataExportRow />)
    await user.click(screen.getByRole('button', { name: 'Export metadata' }))

    expect(chooseExportFile).toHaveBeenCalledWith(expect.stringMatching(/\.jsonl\.gz$/))
    expect(libraryApi.startMetadataExport).toHaveBeenCalledWith('C:\\Backups\\mine.jsonl.gz')
    expect(await screen.findByText('Saved')).toHaveAttribute('title', 'C:\\Backups\\mine.jsonl.gz')
    expect(saveUrl).not.toHaveBeenCalled()
  })

  it('does nothing when the save dialog is cancelled', async () => {
    window.electronAPI = {
      chooseExportFile: vi.fn().mockResolvedValue(null),
    } as unknown as Window['electronAPI']
    const user = userEvent.setup()
    renderWithProviders(<MetadataExportRow />)
    await user.click(screen.getByRole('button', { name: 'Export metadata' }))
    await waitFor(() => expect(window.electronAPI!.chooseExportFile).toHaveBeenCalled())
    expect(libraryApi.startMetadataExport).not.toHaveBeenCalled()
  })

  it('shows progress while it runs, and a failure', async () => {
    const get = vi
      .spyOn(jobApi, 'get')
      .mockResolvedValueOnce(
        job({ status: 'running', progress: 'Exported 10 of 20 images', progress_pct: 50 }),
      )
      .mockResolvedValue(job({ status: 'failed', error: 'disk full' }))
    const user = userEvent.setup()
    renderWithProviders(<MetadataExportRow />)
    await user.click(screen.getByRole('button', { name: 'Export metadata' }))
    expect(await screen.findByText(/Exported 10 of 20 images/)).toBeInTheDocument()
    expect(await screen.findByText('Failed', {}, { timeout: 4000 })).toHaveAttribute(
      'title',
      'disk full',
    )
    expect(get).toHaveBeenCalled()
  })
})
