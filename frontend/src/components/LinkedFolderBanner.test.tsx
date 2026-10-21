import { describe, it, expect, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test/renderWithProviders'
import { libraryApi, type LibraryStatus } from '@/lib/api/libraryApi'
import { LinkedFolderBanner } from './LinkedFolderBanner'

vi.mock('@/lib/api/libraryApi', () => ({ libraryApi: { scan: vi.fn() } }))
vi.mock('@/lib/import/ImportManager', () => ({ getImportManager: () => ({ refresh: vi.fn() }) }))

function status(state: 'online' | 'offline' | 'detached' | null): LibraryStatus {
  return {
    library_id: 'lib',
    linked: state && {
      state,
      name: 'Battle Maps',
      path: null,
      image_count: 10,
      missing_count: 0,
      last_scan_at: null,
      scanning: false,
    },
  }
}

describe('LinkedFolderBanner', () => {
  it("says an offline folder isn't available, and checks it again on request", async () => {
    vi.mocked(libraryApi.scan).mockResolvedValue({ started: true })
    renderWithProviders(<LinkedFolderBanner status={status('offline')} />)
    expect(screen.getByRole('status')).toHaveTextContent("Battle Maps isn't available")
    await userEvent.click(screen.getByRole('button', { name: 'Check again' }))
    await waitFor(() => expect(libraryApi.scan).toHaveBeenCalledWith('manual'))
  })

  it.each(['online', 'detached', null] as const)('is hidden when the folder is %s', (state) => {
    renderWithProviders(<LinkedFolderBanner status={status(state)} />)
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })
})
