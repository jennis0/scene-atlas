import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test/renderWithProviders'
import { libraryApi } from '@/lib/api/libraryApi'
import { jobApi } from '@/lib/api'
import type { BackgroundJob } from '@/types'
import { useLibraryMove } from '@/hooks/useLibraryMove'
import { MoveButton, MoveStatus } from './MoveLibrary'

vi.mock('@/lib/api/libraryApi', () => ({
  libraryApi: { moveStatus: vi.fn(), startMove: vi.fn(), deleteMovedFrom: vi.fn() },
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

function job(over: Partial<BackgroundJob>): BackgroundJob {
  return {
    id: 'job-1',
    name: 'Moving library',
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

function Harness() {
  const move = useLibraryMove(true)
  return (
    <>
      <MoveButton kind="store" move={move} />
      <MoveStatus move={move} />
    </>
  )
}

describe('Move library', () => {
  const applyMove = vi.fn()
  const chooseFolder = vi.fn()
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(libraryApi.moveStatus).mockResolvedValue({ job_id: null, moved_from: null })
    vi.mocked(libraryApi.startMove).mockResolvedValue({ job_id: 'job-1' })
    window.electronAPI = { applyMove, chooseFolder } as unknown as Window['electronAPI']
  })
  afterEach(() => {
    delete window.electronAPI
  })

  it('copies to the folder picked, then restarts on it', async () => {
    chooseFolder.mockResolvedValue('/new/images')
    applyMove.mockReturnValue(new Promise(() => {})) // the page reloads
    vi.spyOn(jobApi, 'get').mockResolvedValue(job({ result: { store: '/new/images' } }))
    const user = userEvent.setup()
    renderWithProviders(<Harness />)
    await user.click(screen.getByRole('button', { name: 'Move imported images folder' }))
    expect(libraryApi.startMove).toHaveBeenCalledWith({ store: '/new/images' })
    await waitFor(() => expect(applyMove).toHaveBeenCalledWith({ store: '/new/images' }))
    expect(screen.getByText(/Restarting on the new folder/)).toBeInTheDocument()
  })

  it('says nothing moved when the copy fails', async () => {
    chooseFolder.mockResolvedValue('/new/images')
    vi.spyOn(jobApi, 'get').mockResolvedValue(
      job({ status: 'failed', error: "1 file(s) didn't copy correctly" }),
    )
    const user = userEvent.setup()
    renderWithProviders(<Harness />)
    await user.click(screen.getByRole('button', { name: 'Move imported images folder' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Nothing has moved')
    expect(applyMove).not.toHaveBeenCalled()
  })

  it('offers to delete the old copy', async () => {
    vi.mocked(libraryApi.moveStatus).mockResolvedValue({
      job_id: null,
      moved_from: { store: '/old/images' },
    })
    vi.mocked(libraryApi.deleteMovedFrom).mockResolvedValue({ deleted: 1 })
    const user = userEvent.setup()
    renderWithProviders(<Harness />)
    expect(await screen.findByText('/old/images')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Delete old copy' }))
    await user.click(screen.getByRole('button', { name: 'Delete' }))
    expect(libraryApi.deleteMovedFrom).toHaveBeenCalled()
  })
})
