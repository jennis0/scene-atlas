import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test/renderWithProviders'
import { LibraryInfoDialog } from './LibraryInfoDialog'

// ── Mock electronAPI ──────────────────────────────────────────────────────────

function makeMockElectronAPI(): NonNullable<Window['electronAPI']> {
  return {
    platform: 'win32',
    onBackendError: vi.fn(),
    getAppDataDir: vi.fn().mockResolvedValue('C:\\Users\\test\\AppData\\Roaming\\Scene Atlas'),
    getImageLibraryDir: vi
      .fn()
      .mockResolvedValue('C:\\Users\\test\\Scene Atlas\\data\\store\\images'),
    chooseAppDataDir: vi.fn().mockResolvedValue(null),
    chooseImageLibraryDir: vi.fn().mockResolvedValue(null),
    changeStorageDirs: vi.fn().mockResolvedValue({ error: null }),
    getPathForFile: vi.fn().mockReturnValue(''),
    chooseImportFolders: vi.fn().mockResolvedValue([]),
    chooseImportFiles: vi.fn().mockResolvedValue([]),
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
        vectors_bytes: 524288, // 512 KB
        metadata_bytes: 262144, // 256 KB
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
  getLibraryExportUrl: vi.fn().mockReturnValue('/api/v1/export'),
}))

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('LibraryInfoDialog', () => {
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
    const { container } = renderWithProviders(<LibraryInfoDialog open={false} onClose={vi.fn()} />)
    expect(container.querySelector('[role="dialog"]')).toBeNull()
  })

  it('displays storage paths in electron mode', async () => {
    renderWithProviders(<LibraryInfoDialog open onClose={vi.fn()} />)
    await waitFor(() => {
      expect(screen.getByText('C:\\Users\\test\\AppData\\Roaming\\Scene Atlas')).toBeInTheDocument()
      expect(
        screen.getByText('C:\\Users\\test\\Scene Atlas\\data\\store\\images'),
      ).toBeInTheDocument()
    })
  })

  it('displays storage sizes when data loads', async () => {
    renderWithProviders(<LibraryInfoDialog open onClose={vi.fn()} />)
    await waitFor(() => {
      expect(screen.getByText('1.8 MB')).toBeInTheDocument() // total in stat card
      expect(screen.getByText('1.0 MB')).toBeInTheDocument() // images in storage bar
      expect(screen.getByText('512 KB')).toBeInTheDocument() // vectors in storage bar
      expect(screen.getByText('256 KB')).toBeInTheDocument() // metadata in storage bar
    })
  })

  it('displays library counts', async () => {
    renderWithProviders(<LibraryInfoDialog open onClose={vi.fn()} />)
    await waitFor(() => {
      expect(screen.getByText('42')).toBeInTheDocument()
      expect(screen.getByText('7')).toBeInTheDocument()
    })
  })

  // ── Tabs ──────────────────────────────────────────────────────────────

  it('has Library, Appearance and Settings tabs; arrow keys cycle and the title follows', async () => {
    const user = userEvent.setup()
    renderWithProviders(<LibraryInfoDialog open onClose={vi.fn()} />)
    const tabs = screen.getAllByRole('tab')
    expect(tabs.map((t) => t.textContent)).toEqual(['Library', 'Appearance', 'Settings'])

    // Tab changes are async (they save Settings first), so wait after each key
    const expectSelected = (name: string) =>
      waitFor(() =>
        expect(screen.getByRole('tab', { name })).toHaveAttribute('aria-selected', 'true'),
      )

    await user.click(tabs[0])
    await user.keyboard('{ArrowRight}')
    await expectSelected('Appearance')
    expect(screen.getByRole('radiogroup', { name: 'Palette' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Appearance' })).toBeInTheDocument()

    await user.keyboard('{ArrowLeft}')
    await expectSelected('Library')
    await user.keyboard('{ArrowLeft}')
    await expectSelected('Settings')
    expect(screen.queryByRole('radiogroup', { name: 'Palette' })).toBeNull()
  })

  // ── Danger Zone tests ────────────────────────────────────────────────────

  it('shows danger zone section with delete and reset buttons', async () => {
    renderWithProviders(<LibraryInfoDialog open onClose={vi.fn()} />)
    await waitFor(() => {
      expect(screen.getByText('Delete library')).toBeInTheDocument()
      expect(screen.getByText('Reset tags')).toBeInTheDocument()
      expect(screen.getByRole('button', { name: /^delete$/i })).toBeInTheDocument()
      expect(screen.getAllByRole('button', { name: /^reset$/i }).length).toBeGreaterThan(0)
    })
  })

  it('shows delete confirmation dialog on Delete button click', async () => {
    const user = userEvent.setup()
    renderWithProviders(<LibraryInfoDialog open onClose={vi.fn()} />)

    await waitFor(() => {
      expect(screen.getByText('Delete library')).toBeInTheDocument()
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
    renderWithProviders(<LibraryInfoDialog open onClose={vi.fn()} />)

    await waitFor(() => {
      expect(screen.getByText('Reset tags')).toBeInTheDocument()
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
