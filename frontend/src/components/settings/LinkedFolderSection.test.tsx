import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { toast } from 'sonner'
import { renderWithProviders } from '@/test/renderWithProviders'
import { libraryApi, type LibraryStatus, type LinkedFolder } from '@/lib/api/libraryApi'
import { settingsApi } from '@/lib/api/settingsApi'
import type { AppSettings } from '@/types'
import { LinkedFolderSection } from './LinkedFolderSection'

const mode = vi.hoisted(() => ({ isApp: true }))
vi.mock('@/lib/appMode', () => ({
  get isApp() {
    return mode.isApp
  },
}))
vi.mock('@/lib/api/libraryApi', () => ({
  libraryApi: {
    status: vi.fn(),
    scan: vi.fn(),
    removeMissing: vi.fn(),
    removeLinked: vi.fn(),
  },
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock('@/lib/api/settingsApi', () => ({ settingsApi: { get: vi.fn(), patch: vi.fn() } }))
const refresh = vi.hoisted(() => vi.fn())
vi.mock('@/lib/import/ImportManager', () => ({ getImportManager: () => ({ refresh }) }))

function withLinked(over: Partial<LinkedFolder> = {}): LibraryStatus {
  return {
    library_id: 'lib',
    linked: {
      state: 'online',
      name: 'Battle Maps',
      path: 'D:\\Battle Maps',
      image_count: 56214,
      missing_count: 0,
      last_scan_at: null,
      scanning: false,
      ...over,
    },
  }
}

const DIRS = { appData: 'C:\\data', store: 'D:\\Battle Maps\\Scene Atlas' }

describe('LinkedFolderSection', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mode.isApp = true
    vi.mocked(settingsApi.get).mockResolvedValue({ linked_rescan_minutes: 15 } as AppSettings)
    vi.mocked(settingsApi.patch).mockResolvedValue({ linked_rescan_minutes: 60 } as AppSettings)
    vi.mocked(libraryApi.scan).mockResolvedValue({ started: true })
    window.electronAPI = {
      getStorageDirs: vi
        .fn()
        .mockResolvedValue({ ...DIRS, linked: 'D:\\Battle Maps', defaults: DIRS }),
      applyLibrary: vi.fn().mockReturnValue(new Promise(() => {})),
    } as unknown as Window['electronAPI']
  })
  afterEach(() => {
    delete window.electronAPI
  })

  it('shows nothing without a linked folder', async () => {
    vi.mocked(libraryApi.status).mockResolvedValue({ library_id: 'lib', linked: null })
    renderWithProviders(<LinkedFolderSection open />)
    await waitFor(() => expect(libraryApi.status).toHaveBeenCalled())
    expect(screen.queryByText('Images folder')).not.toBeInTheDocument()
  })

  it('shows the folder and checks it for changes on request', async () => {
    vi.mocked(libraryApi.status).mockResolvedValue(withLinked())
    const user = userEvent.setup()
    renderWithProviders(<LinkedFolderSection open />)
    expect(await screen.findByText('Battle Maps')).toBeInTheDocument()
    expect(screen.getByText('D:\\Battle Maps')).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('56,214 maps')
    await user.click(screen.getByRole('button', { name: 'Check for changes' }))
    expect(libraryApi.scan).toHaveBeenCalledWith('manual')
    await waitFor(() => expect(refresh).toHaveBeenCalled())
  })

  it('saves how often to check as soon as it changes', async () => {
    vi.mocked(libraryApi.status).mockResolvedValue(withLinked())
    const user = userEvent.setup()
    renderWithProviders(<LinkedFolderSection open />)
    const group = await screen.findByRole('radiogroup', { name: 'How often to check' })
    expect(within(group).getByRole('radio', { name: '15 min' })).toBeChecked()
    await user.click(within(group).getByRole('radio', { name: 'Hourly' }))
    expect(settingsApi.patch).toHaveBeenCalledWith({ linked_rescan_minutes: 60 })
    await waitFor(() => expect(within(group).getByRole('radio', { name: 'Hourly' })).toBeChecked())
  })

  it('says when the folder is offline, and while it is being checked', async () => {
    vi.mocked(libraryApi.status).mockResolvedValue(withLinked({ state: 'offline' }))
    const { unmount } = renderWithProviders(<LinkedFolderSection open />)
    expect(await screen.findByRole('status')).toHaveTextContent("Battle Maps isn't available")
    unmount()
    vi.mocked(libraryApi.status).mockResolvedValue(withLinked({ scanning: true }))
    renderWithProviders(<LinkedFolderSection open />)
    expect(await screen.findByRole('status')).toHaveTextContent('Checking for changes…')
    expect(screen.getByRole('button', { name: 'Check for changes' })).toBeDisabled()
  })

  it('removes maps whose files are missing, after confirming', async () => {
    vi.mocked(libraryApi.status).mockResolvedValue(withLinked({ missing_count: 12 }))
    vi.mocked(libraryApi.removeMissing).mockResolvedValue({ removed: 12 })
    const user = userEvent.setup()
    renderWithProviders(<LinkedFolderSection open />)
    expect(await screen.findByText('12 maps are missing')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Remove missing maps' }))
    expect(libraryApi.removeMissing).not.toHaveBeenCalled()
    const dialog = screen.getByRole('dialog', { name: 'Remove missing maps?' })
    expect(dialog).toHaveTextContent('removes the 12 maps whose files are gone')
    await user.click(within(dialog).getByRole('button', { name: 'Remove missing maps' }))
    await waitFor(() => expect(libraryApi.removeMissing).toHaveBeenCalled())
  })

  it('stops using the folder after confirming the count, then restarts without it', async () => {
    vi.mocked(libraryApi.status).mockResolvedValue(withLinked())
    vi.mocked(libraryApi.removeLinked).mockResolvedValue({ removed: 56214 })
    const user = userEvent.setup()
    renderWithProviders(<LinkedFolderSection open />)
    await user.click(await screen.findByRole('button', { name: 'Stop using' }))
    const dialog = screen.getByRole('dialog', { name: 'Stop using this folder?' })
    expect(dialog).toHaveTextContent('removes the 56,214 maps in Battle Maps')
    expect(libraryApi.removeLinked).not.toHaveBeenCalled()
    await user.click(within(dialog).getByRole('button', { name: 'Stop using this folder' }))
    await waitFor(() =>
      expect(window.electronAPI!.applyLibrary).toHaveBeenCalledWith({
        appData: DIRS.appData,
        store: DIRS.store,
        linked: null,
      }),
    )
    expect(libraryApi.removeLinked).toHaveBeenCalled()
  })

  it("keeps the folder configured when its maps couldn't be removed", async () => {
    vi.mocked(libraryApi.status).mockResolvedValue(withLinked())
    vi.mocked(libraryApi.removeLinked).mockRejectedValue(new Error('The library is busy.'))
    const user = userEvent.setup()
    renderWithProviders(<LinkedFolderSection open />)
    await user.click(await screen.findByRole('button', { name: 'Stop using' }))
    await user.click(screen.getByRole('button', { name: 'Stop using this folder' }))
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('The library is busy.'))
    expect(window.electronAPI!.applyLibrary).not.toHaveBeenCalled()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('says why when the desktop app refuses to drop the folder, and shows the maps gone', async () => {
    vi.mocked(libraryApi.status).mockResolvedValue(withLinked())
    vi.mocked(libraryApi.removeLinked).mockResolvedValue({ removed: 56214 })
    vi.mocked(window.electronAPI!.applyLibrary).mockResolvedValue({
      error: "Couldn't save the settings.",
      restarted: false,
    })
    const user = userEvent.setup()
    renderWithProviders(<LinkedFolderSection open />)
    await user.click(await screen.findByRole('button', { name: 'Stop using' }))
    vi.mocked(libraryApi.status).mockResolvedValue(withLinked({ state: 'detached' }))
    await user.click(screen.getByRole('button', { name: 'Stop using this folder' }))
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Couldn't save the settings."))
    expect(await screen.findByRole('status')).toHaveTextContent('no longer used')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('on a server, shows the state and counts but not the path or Stop using', async () => {
    mode.isApp = false
    vi.mocked(libraryApi.status).mockResolvedValue(withLinked({ path: null, missing_count: 3 }))
    renderWithProviders(<LinkedFolderSection open />)
    expect(await screen.findByText('Battle Maps')).toBeInTheDocument()
    expect(screen.getByText('3 maps are missing')).toBeInTheDocument()
    expect(screen.queryByText('D:\\Battle Maps')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Stop using' })).not.toBeInTheDocument()
  })

  it("offers to remove a detached folder's maps", async () => {
    vi.mocked(libraryApi.status).mockResolvedValue(withLinked({ state: 'detached' }))
    vi.mocked(libraryApi.removeLinked).mockResolvedValue({ removed: 56214 })
    const user = userEvent.setup()
    renderWithProviders(<LinkedFolderSection open />)
    expect(await screen.findByRole('status')).toHaveTextContent('no longer used')
    expect(screen.queryByRole('button', { name: 'Check for changes' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Remove its maps' }))
    await user.click(screen.getByRole('button', { name: 'Remove maps' }))
    await waitFor(() => expect(libraryApi.removeLinked).toHaveBeenCalled())
    expect(window.electronAPI!.applyLibrary).not.toHaveBeenCalled()
  })
})
