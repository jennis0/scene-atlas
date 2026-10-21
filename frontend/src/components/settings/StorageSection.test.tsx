import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test/renderWithProviders'
import { libraryApi, type InspectResult } from '@/lib/api/libraryApi'
import { StorageSection } from './StorageSection'

vi.mock('@/lib/api/libraryApi', () => ({
  libraryApi: { status: vi.fn(), inspect: vi.fn() },
}))

const DIRS = { appData: 'C:\\data', store: 'C:\\images' }
const inspect = vi.mocked(libraryApi.inspect)

function result(over: Partial<InspectResult> = {}): InspectResult {
  return {
    outcome: 'open',
    message: null,
    linked: null,
    library: null,
    store_has_maps: false,
    ...over,
  }
}

let api: { chooseFolder: ReturnType<typeof vi.fn>; applyLibrary: ReturnType<typeof vi.fn> }

describe('StorageSection', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(libraryApi.status).mockResolvedValue({ library_id: 'lib', linked: null })
    inspect.mockResolvedValue(result())
    api = {
      chooseFolder: vi.fn().mockResolvedValue(null),
      applyLibrary: vi.fn().mockReturnValue(new Promise(() => {})),
    }
    window.electronAPI = {
      getStorageDirs: vi.fn().mockResolvedValue({ ...DIRS, linked: null, defaults: DIRS }),
      ...api,
    } as unknown as Window['electronAPI']
  })
  afterEach(() => {
    delete window.electronAPI
  })

  it('lists the three folders, with no maps folder yet', async () => {
    renderWithProviders(<StorageSection open />)
    expect(await screen.findByText('C:\\data')).toBeInTheDocument()
    expect(screen.getByText('C:\\images')).toBeInTheDocument()
    expect(screen.getByText('None')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Choose images folder' })).toBeInTheDocument()
    expect(inspect).not.toHaveBeenCalled()
    // Nothing to restart for until a folder changes
    expect(screen.getAllByText('Applies after a restart')).toHaveLength(3)
    expect(screen.queryByRole('button', { name: 'Restart to apply' })).not.toBeInTheDocument()
  })

  it('checks a changed folder, then restarts on it', async () => {
    api.chooseFolder.mockResolvedValueOnce('E:\\images')
    const user = userEvent.setup()
    renderWithProviders(<StorageSection open />)
    await screen.findByText('C:\\images')
    await user.click(screen.getByRole('button', { name: 'Change imported images folder' }))

    expect(api.chooseFolder).toHaveBeenCalledWith('store', 'C:\\images')
    expect(screen.getByText(/doesn't move your files/)).toBeInTheDocument()
    const restart = screen.getByRole('button', { name: 'Restart to apply' })
    await waitFor(() => expect(restart).toBeEnabled())
    expect(inspect).toHaveBeenCalledWith({ app_data: 'C:\\data', store: 'E:\\images' })
    await user.click(restart)
    expect(api.applyLibrary).toHaveBeenCalledWith({
      appData: 'C:\\data',
      store: 'E:\\images',
      linked: null,
    })
    expect(screen.getByRole('button', { name: 'Restarting…' })).toBeDisabled()
  })

  it('links a folder without the move warning', async () => {
    api.chooseFolder.mockResolvedValueOnce('D:\\Maps')
    const user = userEvent.setup()
    renderWithProviders(<StorageSection open />)
    await screen.findByText('None')
    await user.click(screen.getByRole('button', { name: 'Choose images folder' }))
    await waitFor(() =>
      expect(inspect).toHaveBeenCalledWith({
        app_data: 'C:\\data',
        store: 'C:\\images',
        linked: 'D:\\Maps',
      }),
    )
    expect(screen.queryByText(/doesn't move your files/)).not.toBeInTheDocument()
  })

  it('refuses folders the check rejects', async () => {
    inspect.mockResolvedValue(
      result({ outcome: 'error', message: 'The image folder belongs to a different library.' }),
    )
    api.chooseFolder.mockResolvedValueOnce('E:\\images')
    const user = userEvent.setup()
    renderWithProviders(<StorageSection open />)
    await screen.findByText('C:\\images')
    await user.click(screen.getByRole('button', { name: 'Change imported images folder' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('belongs to a different library')
    expect(screen.getByRole('button', { name: 'Restart to apply' })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})
