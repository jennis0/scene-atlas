import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test/renderWithProviders'
import { SystemInfoDialog } from './SystemInfoDialog'

// ── Mock electronAPI ──────────────────────────────────────────────────────────

function makeMockElectronAPI() {
  return {
    onBackendReady: vi.fn(),
    onBackendError: vi.fn(),
    getDataDir: vi.fn().mockResolvedValue('C:\\Users\\test\\Scene Atlas\\data'),
    openDataDir: vi.fn().mockResolvedValue(undefined),
    chooseDataDir: vi.fn().mockResolvedValue(null),
    changeDataDir: vi.fn().mockResolvedValue(undefined),
    readDirectory: vi.fn(),
    readFileBytes: vi.fn(),
  }
}

// ── Mock the API modules ─────────────────────────────────────────────────────

vi.mock('@/lib/api', () => ({
  systemApi: {
    getInfo: vi.fn().mockResolvedValue({
      storage_path: 'C:\\Users\\test\\Scene Atlas\\data',
      mode: 'app',
      storage: {
        images_bytes: 1048576, // 1 MB
        thumbnails_bytes: 524288, // 512 KB
        qdrant_bytes: 262144, // 256 KB
        total_bytes: 1835008,
      },
      library: {
        image_count: 42,
        group_count: 7,
      },
    }),
    deleteLibrary: vi.fn().mockResolvedValue({ job_id: 'test-purge-1', message: 'ok' }),
    resetTags: vi.fn().mockResolvedValue({
      deleted_tags: 100,
      deleted_categories: 10,
      seeded_categories: 10,
    }),
  },
  jobApi: {
    get: vi.fn().mockResolvedValue({
      id: 'test-purge-1',
      name: 'Purge library',
      status: 'running',
      progress: 'Deleting tags and colors',
      progress_pct: 16,
      error: null,
    }),
  },
}))

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('SystemInfoDialog', () => {
  let mockAPI: ReturnType<typeof makeMockElectronAPI>

  beforeEach(() => {
    mockAPI = makeMockElectronAPI()
    ;(window as any).electronAPI = mockAPI
  })

  afterEach(() => {
    delete (window as any).electronAPI
    vi.clearAllMocks()
  })

  it('renders nothing when open=false', () => {
    const { container } = renderWithProviders(<SystemInfoDialog open={false} onClose={vi.fn()} />)
    expect(container.querySelector('[role="dialog"]')).toBeNull()
  })

  it('displays the data directory path', async () => {
    renderWithProviders(<SystemInfoDialog open onClose={vi.fn()} />)
    await waitFor(() => {
      expect(screen.getByText('C:\\Users\\test\\Scene Atlas\\data')).toBeInTheDocument()
    })
  })

  it('displays storage sizes when data loads', async () => {
    renderWithProviders(<SystemInfoDialog open onClose={vi.fn()} />)
    await waitFor(() => {
      expect(screen.getByText('1.0 MB')).toBeInTheDocument() // images
      expect(screen.getByText('512.0 KB')).toBeInTheDocument() // thumbnails
      expect(screen.getByText('256.0 KB')).toBeInTheDocument() // qdrant
      expect(screen.getByText('1.8 MB')).toBeInTheDocument() // total
    })
  })

  it('displays library counts', async () => {
    renderWithProviders(<SystemInfoDialog open onClose={vi.fn()} />)
    await waitFor(() => {
      expect(screen.getByText('42')).toBeInTheDocument()
      expect(screen.getByText('7')).toBeInTheDocument()
    })
  })

  it('calls openDataDir when Open button is clicked', async () => {
    const user = userEvent.setup()
    renderWithProviders(<SystemInfoDialog open onClose={vi.fn()} />)

    // Wait for dataDir to load (buttons are disabled until then)
    await waitFor(() => {
      expect(screen.getByText('C:\\Users\\test\\Scene Atlas\\data')).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: /open/i }))
    expect(mockAPI.openDataDir).toHaveBeenCalled()
  })

  it('shows confirm panel when Change Location picks a new directory', async () => {
    const user = userEvent.setup()
    mockAPI.chooseDataDir.mockResolvedValue('D:\\NewLocation\\data')

    renderWithProviders(<SystemInfoDialog open onClose={vi.fn()} />)

    await waitFor(() => {
      expect(screen.getByText('C:\\Users\\test\\Scene Atlas\\data')).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: /change location/i }))

    await waitFor(() => {
      expect(screen.getByText('D:\\NewLocation\\data')).toBeInTheDocument()
      expect(screen.getByRole('button', { name: /restart/i })).toBeInTheDocument()
    })
  })

  it('returns to idle when Cancel is clicked in confirm state', async () => {
    const user = userEvent.setup()
    mockAPI.chooseDataDir.mockResolvedValue('D:\\NewLocation\\data')

    renderWithProviders(<SystemInfoDialog open onClose={vi.fn()} />)

    await waitFor(() => {
      expect(screen.getByText('C:\\Users\\test\\Scene Atlas\\data')).toBeInTheDocument()
    })

    // Enter confirm state
    await user.click(screen.getByRole('button', { name: /change location/i }))
    await waitFor(() => {
      expect(screen.getByText('D:\\NewLocation\\data')).toBeInTheDocument()
    })

    // Cancel
    await user.click(screen.getByRole('button', { name: /cancel/i }))

    // Should be back to idle — Open button is visible again
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /open/i })).toBeInTheDocument()
    })
  })

  it('calls changeDataDir and shows restarting state on confirm', async () => {
    const user = userEvent.setup()
    // Make changeDataDir hang so we can observe the restarting state
    mockAPI.changeDataDir.mockReturnValue(new Promise(() => {}))
    mockAPI.chooseDataDir.mockResolvedValue('D:\\NewLocation\\data')

    renderWithProviders(<SystemInfoDialog open onClose={vi.fn()} />)

    await waitFor(() => {
      expect(screen.getByText('C:\\Users\\test\\Scene Atlas\\data')).toBeInTheDocument()
    })

    // Enter confirm state
    await user.click(screen.getByRole('button', { name: /change location/i }))
    await waitFor(() => {
      expect(screen.getByText('D:\\NewLocation\\data')).toBeInTheDocument()
    })

    // Click Restart & Apply
    await user.click(screen.getByRole('button', { name: /restart/i }))

    await waitFor(() => {
      expect(screen.getByText(/restarting/i)).toBeInTheDocument()
    })
    expect(mockAPI.changeDataDir).toHaveBeenCalledWith('D:\\NewLocation\\data')
  })

  // ── Danger Zone tests ────────────────────────────────────────────────────

  it('shows danger zone section with delete and reset buttons', async () => {
    renderWithProviders(<SystemInfoDialog open onClose={vi.fn()} />)
    await waitFor(() => {
      expect(screen.getByText('Danger Zone')).toBeInTheDocument()
      expect(screen.getByText('Delete library')).toBeInTheDocument()
      expect(screen.getByText('Reset tags')).toBeInTheDocument()
    })
  })

  it('shows delete confirmation dialog on Delete button click', async () => {
    const user = userEvent.setup()
    renderWithProviders(<SystemInfoDialog open onClose={vi.fn()} />)

    await waitFor(() => {
      expect(screen.getByText('Danger Zone')).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: /^delete$/i }))

    await waitFor(() => {
      expect(screen.getByText('Delete Library')).toBeInTheDocument()
      expect(screen.getByText(/permanently delete all images/i)).toBeInTheDocument()
      expect(screen.getByRole('button', { name: /delete everything/i })).toBeInTheDocument()
    })
  })

  it('shows reset tags confirmation dialog on Reset button click', async () => {
    const user = userEvent.setup()
    renderWithProviders(<SystemInfoDialog open onClose={vi.fn()} />)

    await waitFor(() => {
      expect(screen.getByText('Danger Zone')).toBeInTheDocument()
    })

    // Find the Reset button inside the danger zone (near "Reset tags" label)
    const resetButtons = screen.getAllByRole('button', { name: /^reset$/i })
    // Click the one that's the trigger (not inside a closed dialog)
    await user.click(resetButtons[0])

    await waitFor(() => {
      // Title + confirm button both show "Reset Tags" — just check the description
      expect(screen.getByText(/delete all tags from every image/i)).toBeInTheDocument()
      expect(screen.getByRole('button', { name: /reset tags/i })).toBeInTheDocument()
    })
  })
})
