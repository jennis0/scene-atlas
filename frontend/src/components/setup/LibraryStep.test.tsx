import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { libraryApi, type InspectRequest, type InspectResult } from '@/lib/api/libraryApi'
import { LibraryStep } from './LibraryStep'

vi.mock('@/lib/api/libraryApi', () => ({ libraryApi: { inspect: vi.fn(), status: vi.fn() } }))

const inspect = vi.mocked(libraryApi.inspect)

const DEFAULTS = {
  appData: 'C:\\Users\\me\\AppData\\Local\\Scene Atlas\\data',
  store: 'C:\\Users\\me\\Documents\\Scene Atlas\\images',
}
const LINKED_EXPLAINER = /Scene Atlas adds the maps and scenes in this folder/

/** The provisional library the wizard runs on has a marker of its own */
const CURRENT = { library_id: 'current', setup_completed: false, hints: hints() }

function hints(over: Partial<NonNullable<InspectResult['library']>['hints']> = {}) {
  return { app_data: null, store: null, linked: null, ...over }
}

/** Answer for *body*: an empty linked folder and the running library, unless overridden */
function answer(body: InspectRequest, over: Partial<InspectResult> = {}): InspectResult {
  return {
    outcome: 'new',
    message: null,
    linked: body.linked ? { kind: 'empty', image_count: 0, capped: false } : null,
    library: CURRENT,
    store_has_maps: false,
    ...over,
  }
}

function respond(fn: (body: InspectRequest) => Partial<InspectResult>) {
  inspect.mockImplementation(async (body) => answer(body, fn(body)))
}

let api: {
  chooseFolder: ReturnType<typeof vi.fn>
  applyLibrary: ReturnType<typeof vi.fn>
}

function renderStep() {
  const onNext = vi.fn()
  render(<LibraryStep nav={{ steps: ['library', 'format'], index: 0, onNext }} />)
  return onNext
}

const continueButton = () => screen.getByRole('button', { name: 'Continue' })
const pickLinked = async (user: ReturnType<typeof userEvent.setup>, folder: string) => {
  api.chooseFolder.mockResolvedValueOnce(folder)
  await user.click(await screen.findByRole('radio', { name: /Use a folder of images/ }))
  await user.click(screen.getByRole('button', { name: 'Choose your images folder' }))
}

describe('LibraryStep', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(libraryApi.status).mockResolvedValue({ library_id: 'current', linked: null })
    respond(() => ({}))
    api = {
      chooseFolder: vi.fn().mockResolvedValue(null),
      applyLibrary: vi.fn().mockResolvedValue({ error: null, restarted: false }),
    }
    window.electronAPI = {
      platform: 'win32',
      libraryChosen: false,
      getStorageDirs: vi.fn().mockResolvedValue({ ...DEFAULTS, linked: null, defaults: DEFAULTS }),
      ...api,
    } as unknown as Window['electronAPI']
  })

  afterEach(() => {
    delete window.electronAPI
  })

  it('starts a new library on the default folders, moving on when nothing restarts', async () => {
    const user = userEvent.setup()
    const onNext = renderStep()
    expect(await screen.findByRole('radio', { name: 'Start a new library' })).toBeChecked()
    expect(screen.getByText(DEFAULTS.store)).toBeInTheDocument()
    expect(screen.getByText(DEFAULTS.appData)).toBeInTheDocument()
    await waitFor(() => expect(continueButton()).toBeEnabled())
    // The provisional library's own marker isn't "a library found"
    expect(screen.queryByText('Scene Atlas library found.')).not.toBeInTheDocument()
    expect(inspect).toHaveBeenCalledWith({ app_data: DEFAULTS.appData, store: DEFAULTS.store })

    await user.click(continueButton())
    expect(api.applyLibrary).toHaveBeenCalledWith({
      appData: DEFAULTS.appData,
      store: DEFAULTS.store,
      linked: null,
    })
    expect(onNext).toHaveBeenCalled()
  })

  it('explains the linked option only once it is selected, and needs a folder', async () => {
    const user = userEvent.setup()
    renderStep()
    await screen.findByRole('radio', { name: 'Start a new library' })
    expect(screen.queryByText(LINKED_EXPLAINER)).not.toBeInTheDocument()
    await user.click(screen.getByRole('radio', { name: /Use a folder of images/ }))
    expect(screen.getByText(LINKED_EXPLAINER)).toBeVisible()
    expect(screen.getByText('No folder chosen')).toBeInTheDocument()
    expect(continueButton()).toBeDisabled()
  })

  it('counts the images in a maps folder and keeps imported maps inside it', async () => {
    respond((body) =>
      body.linked ? { linked: { kind: 'maps', image_count: 56214, capped: false } } : {},
    )
    const user = userEvent.setup()
    const onNext = renderStep()
    await pickLinked(user, 'D:\\Battle Maps\\')

    expect(await screen.findByText('Found 56,214 images.')).toBeInTheDocument()
    expect(screen.getByText('D:\\Battle Maps\\Scene Atlas')).toBeInTheDocument()
    expect(api.chooseFolder).toHaveBeenCalledWith('linked', undefined)
    await waitFor(() => expect(continueButton()).toBeEnabled())
    await user.click(continueButton())
    expect(api.applyLibrary).toHaveBeenCalledWith({
      appData: DEFAULTS.appData,
      store: 'D:\\Battle Maps\\Scene Atlas',
      linked: 'D:\\Battle Maps\\',
    })
    expect(onNext).toHaveBeenCalled()
  })

  it('says when counting stopped at the limit', async () => {
    respond((body) =>
      body.linked ? { linked: { kind: 'maps', image_count: 250000, capped: true } } : {},
    )
    const user = userEvent.setup()
    renderStep()
    await pickLinked(user, 'D:\\Huge')
    expect(await screen.findByText('Found more than 250,000 images.')).toBeInTheDocument()
  })

  it('shows nothing for an empty folder, and allows Continue', async () => {
    const user = userEvent.setup()
    renderStep()
    await pickLinked(user, 'D:\\New Maps')
    await waitFor(() => expect(continueButton()).toBeEnabled())
    expect(screen.queryByText(/^Found/)).not.toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('opens a library found in the folder, filling in the other folders from its hints', async () => {
    const found = {
      library_id: 'other',
      setup_completed: true,
      hints: hints({
        app_data: 'E:\\Atlas\\data',
        store: 'D:\\Maps\\Scene Atlas',
        linked: 'D:\\Maps',
      }),
    }
    respond((body) =>
      body.linked === 'D:\\Maps'
        ? {
            outcome: 'open',
            library: found,
            linked: { kind: 'library', image_count: 0, capped: false },
          }
        : {},
    )
    const user = userEvent.setup()
    renderStep()
    await pickLinked(user, 'D:\\Maps')

    expect(await screen.findByText('Scene Atlas library found.')).toBeInTheDocument()
    expect(await screen.findByText('E:\\Atlas\\data')).toBeInTheDocument()
    // Checked again with the hinted folders before it can be opened
    await waitFor(() => expect(screen.getByRole('button', { name: 'Open library' })).toBeEnabled())
    await user.click(screen.getByRole('button', { name: 'Open library' }))
    expect(api.applyLibrary).toHaveBeenCalledWith({
      appData: 'E:\\Atlas\\data',
      store: 'D:\\Maps\\Scene Atlas',
      linked: 'D:\\Maps',
    })
  })

  it('opens a library without a linked folder as it is, when its folder is picked', async () => {
    const found = {
      library_id: 'other',
      setup_completed: true,
      hints: hints({ app_data: 'E:\\Atlas\\data', store: 'E:\\Atlas\\images' }),
    }
    respond((body) =>
      body.linked === 'E:\\Atlas\\images'
        ? {
            outcome: 'open',
            library: found,
            linked: { kind: 'library', image_count: 0, capped: false },
          }
        : body.store === 'E:\\Atlas\\images'
          ? { outcome: 'open', library: found }
          : {},
    )
    const user = userEvent.setup()
    renderStep()
    await pickLinked(user, 'E:\\Atlas\\images')

    await waitFor(() =>
      expect(screen.getByRole('radio', { name: 'Start a new library' })).toBeChecked(),
    )
    expect(await screen.findByText('Scene Atlas library found.')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Open library' })).toBeEnabled())
    await user.click(screen.getByRole('button', { name: 'Open library' }))
    expect(api.applyLibrary).toHaveBeenCalledWith({
      appData: 'E:\\Atlas\\data',
      store: 'E:\\Atlas\\images',
      linked: null,
    })
  })

  it("drops a found library's folders when another maps folder is picked", async () => {
    const found = {
      library_id: 'other',
      setup_completed: true,
      hints: hints({ app_data: 'E:\\Atlas\\data', store: 'E:\\Atlas\\images', linked: 'D:\\Maps' }),
    }
    respond((body) =>
      body.linked === 'D:\\Maps'
        ? {
            outcome: 'open',
            library: found,
            linked: { kind: 'library', image_count: 0, capped: false },
          }
        : {},
    )
    const user = userEvent.setup()
    renderStep()
    await pickLinked(user, 'D:\\Maps')
    expect(await screen.findByText('E:\\Atlas\\data')).toBeInTheDocument()

    api.chooseFolder.mockResolvedValueOnce('D:\\Other')
    await user.click(screen.getByRole('button', { name: 'Choose your images folder' }))
    expect(await screen.findByText(DEFAULTS.appData)).toBeInTheDocument()
    expect(screen.getByText('D:\\Other\\Scene Atlas')).toBeInTheDocument()
    await waitFor(() => expect(continueButton()).toBeEnabled())
    await user.click(continueButton())
    expect(api.applyLibrary).toHaveBeenCalledWith({
      appData: DEFAULTS.appData,
      store: 'D:\\Other\\Scene Atlas',
      linked: 'D:\\Other',
    })
  })

  it('starts from the folders the desktop app is already using', async () => {
    vi.mocked(window.electronAPI!.getStorageDirs).mockResolvedValue({
      appData: 'E:\\data',
      store: 'D:\\Maps\\Scene Atlas',
      linked: 'D:\\Maps',
      defaults: DEFAULTS,
    })
    const user = userEvent.setup()
    renderStep()
    // The radio renders before the folders arrive; it's checked once they have
    expect(await screen.findByText('E:\\data')).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: /Use a folder of images/ })).toBeChecked()
    await waitFor(() => expect(continueButton()).toBeEnabled())
    await user.click(continueButton())
    expect(api.applyLibrary).toHaveBeenCalledWith({
      appData: 'E:\\data',
      store: 'D:\\Maps\\Scene Atlas',
      linked: 'D:\\Maps',
    })
  })

  it.each([
    "This library's search data folder is missing. Choose it, or pick another folder.",
    'These folders belong to different libraries.',
  ])('blocks Continue and says why: %s', async (message) => {
    respond((body) => (body.linked ? { outcome: 'error', message } : {}))
    const user = userEvent.setup()
    renderStep()
    await pickLinked(user, 'D:\\Maps')
    expect(await screen.findByRole('alert')).toHaveTextContent(message)
    expect(continueButton()).toBeDisabled()
  })

  it('offers a maps folder picked for imported maps as the existing folder', async () => {
    respond((body) => ({ store_has_maps: body.store === 'D:\\Battle Maps' }))
    api.chooseFolder.mockResolvedValueOnce('D:\\Battle Maps')
    const user = userEvent.setup()
    renderStep()
    await user.click(await screen.findByRole('button', { name: 'Change Imported images folder' }))

    expect(await screen.findByText('This folder already has images in it.')).toBeInTheDocument()
    await waitFor(() => expect(continueButton()).toBeEnabled())
    await user.click(screen.getByRole('button', { name: 'Use it as your existing folder' }))

    expect(screen.getByRole('radio', { name: /Use a folder of images/ })).toBeChecked()
    expect(screen.getByText('D:\\Battle Maps')).toBeInTheDocument()
    expect(screen.getByText('D:\\Battle Maps\\Scene Atlas')).toBeInTheDocument()
    await waitFor(() =>
      expect(screen.queryByText('This folder already has images in it.')).not.toBeInTheDocument(),
    )
  })

  it('stays busy while the desktop app restarts on the new folders', async () => {
    api.applyLibrary.mockReturnValue(new Promise(() => {}))
    const user = userEvent.setup()
    const onNext = renderStep()
    await pickLinked(user, 'D:\\Maps')
    await waitFor(() => expect(continueButton()).toBeEnabled())
    await user.click(continueButton())
    expect(screen.getByRole('button', { name: 'Working…' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Choose your images folder' })).toBeDisabled()
    expect(onNext).not.toHaveBeenCalled()
  })

  it('shows why the desktop app refused the folders', async () => {
    api.applyLibrary.mockResolvedValue({ error: "Couldn't write to D:\\Maps.", restarted: false })
    const user = userEvent.setup()
    const onNext = renderStep()
    await pickLinked(user, 'D:\\Maps')
    await waitFor(() => expect(continueButton()).toBeEnabled())
    await user.click(continueButton())
    expect(await screen.findByRole('alert')).toHaveTextContent("Couldn't write to D:\\Maps.")
    expect(onNext).not.toHaveBeenCalled()
  })

  it('lets the user retry when the folders could not be checked', async () => {
    inspect.mockRejectedValueOnce(new Error('offline'))
    const user = userEvent.setup()
    renderStep()
    expect(await screen.findByRole('alert')).toHaveTextContent("Couldn't check these folders.")
    expect(continueButton()).toBeDisabled()
    await user.click(screen.getByRole('button', { name: 'Try again' }))
    await waitFor(() => expect(continueButton()).toBeEnabled())
  })
})
