import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { act, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { AppUpdateState } from '@/electron'
import type { ServerUpdateStatus } from '@/lib/api/systemApi'
import { renderWithProviders as render } from '@/test/renderWithProviders'
import { UpdatesSection } from './UpdatesSection'
import { UpdateNotifier } from '@/components/UpdateNotifier'

const toastInfo = vi.hoisted(() => vi.fn())
vi.mock('sonner', () => ({ toast: { info: toastInfo } }))

const getUpdates = vi.hoisted(() => vi.fn())
vi.mock('@/lib/api/systemApi', () => ({ systemApi: { getUpdates } }))

const BASE: AppUpdateState = {
  status: 'up-to-date',
  mode: 'install',
  currentVersion: '0.1.0',
  checksEnabled: true,
}

const RELEASES = 'https://github.com/jennis0/scene-atlas/releases'
const SERVER: ServerUpdateStatus = {
  status: 'up_to_date',
  current_version: '0.2.0',
  checks_enabled: true,
  latest_version: '0.2.0',
  update_available: false,
  release_url: `${RELEASES}/tag/v0.2.0`,
  last_checked: '2026-10-19T12:00:00Z',
}
const SERVER_AVAILABLE: ServerUpdateStatus = {
  ...SERVER,
  status: 'available',
  latest_version: '0.3.0',
  update_available: true,
  release_url: `${RELEASES}/tag/v0.3.0`,
}

/** A fake updater bridge whose pushed states the test controls. */
function installUpdateApi(initial: AppUpdateState | null) {
  let push: ((state: AppUpdateState) => void) | null = null
  const api = {
    getUpdateState: vi.fn().mockResolvedValue(initial),
    checkForUpdates: vi.fn().mockResolvedValue({ ...initial, status: 'checking' }),
    setUpdatesEnabled: vi.fn((enabled: boolean) =>
      Promise.resolve({ ...initial, checksEnabled: enabled }),
    ),
    installUpdate: vi.fn().mockResolvedValue(undefined),
    openUpdateDownload: vi.fn().mockResolvedValue(undefined),
    onUpdateState: vi.fn((callback: (state: AppUpdateState) => void) => {
      push = callback
      return () => {
        push = null
      }
    }),
  }
  ;(window as { electronAPI?: unknown }).electronAPI = api
  return { api, push: (state: AppUpdateState) => act(() => push?.(state)) }
}

afterEach(() => {
  delete (window as { electronAPI?: unknown }).electronAPI
})

beforeEach(() => {
  toastInfo.mockReset()
  getUpdates.mockReset()
  // A server that hasn't answered yet
  getUpdates.mockReturnValue(new Promise(() => {}))
  localStorage.clear()
})

describe('UpdatesSection', () => {
  it('renders nothing until the server answers, or in a desktop dev build', async () => {
    const { container, unmount } = render(<UpdatesSection />)
    expect(container).toBeEmptyDOMElement()
    unmount()

    installUpdateApi({ ...BASE, status: 'unsupported' })
    const dev = render(<UpdatesSection />)
    await waitFor(() => expect(window.electronAPI!.getUpdateState).toHaveBeenCalled())
    expect(dev.container).toBeEmptyDOMElement()
  })

  it("doesn't ask the server in the desktop app", async () => {
    installUpdateApi(BASE)
    render(<UpdatesSection />)
    await screen.findByText('Version 0.1.0')
    expect(getUpdates).not.toHaveBeenCalled()
  })

  it('shows the version and checks on request', async () => {
    const { api } = installUpdateApi(BASE)
    render(<UpdatesSection />)
    expect(await screen.findByText('Version 0.1.0')).toBeInTheDocument()
    expect(screen.getAllByText('Up to date.').length).toBeGreaterThan(0)

    await userEvent.click(screen.getByRole('button', { name: 'Check now' }))
    expect(api.checkForUpdates).toHaveBeenCalled()
    expect(await screen.findByRole('button', { name: 'Check now' })).toBeDisabled()
  })

  it('turns automatic checks off', async () => {
    const { api } = installUpdateApi(BASE)
    render(<UpdatesSection />)
    const toggle = await screen.findByRole('button', { name: 'Check for updates automatically' })
    expect(toggle).toHaveAttribute('aria-pressed', 'true')
    await userEvent.click(toggle)
    expect(api.setUpdatesEnabled).toHaveBeenCalledWith(false)
    await waitFor(() => expect(toggle).toHaveAttribute('aria-pressed', 'false'))
  })

  it('offers a restart once the update is downloaded', async () => {
    const { api, push } = installUpdateApi(BASE)
    render(<UpdatesSection />)
    await screen.findByText('Version 0.1.0')
    push({ ...BASE, status: 'downloading', version: '0.2.0', percent: 40 })
    expect(screen.getAllByText('Downloading version 0.2.0 (40%)').length).toBeGreaterThan(0)

    push({ ...BASE, status: 'ready', version: '0.2.0', percent: 100 })
    await userEvent.click(screen.getByRole('button', { name: 'Restart to update' }))
    expect(api.installUpdate).toHaveBeenCalled()
  })

  it('links to the download where the app can only notify', async () => {
    const { api } = installUpdateApi({
      ...BASE,
      mode: 'notify',
      status: 'available',
      version: '0.2.0',
    })
    render(<UpdatesSection />)
    await userEvent.click(await screen.findByRole('button', { name: 'Download' }))
    expect(api.openUpdateDownload).toHaveBeenCalled()
  })

  it('shows why a check failed', async () => {
    installUpdateApi({ ...BASE, status: 'error', error: "Couldn't check for updates." })
    render(<UpdatesSection />)
    expect((await screen.findAllByText("Couldn't check for updates.")).length).toBeGreaterThan(0)
    expect(screen.getByRole('button', { name: 'Check now' })).toBeEnabled()
  })
})

describe('UpdatesSection on a server', () => {
  it('shows the version, with no controls', async () => {
    getUpdates.mockResolvedValue(SERVER)
    render(<UpdatesSection />)
    expect(await screen.findByText('Version 0.2.0')).toBeInTheDocument()
    expect(screen.getAllByText('Up to date.').length).toBeGreaterThan(0)
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
  })

  it('links to the release notes and the upgrade guide when a version is out', async () => {
    getUpdates.mockResolvedValue(SERVER_AVAILABLE)
    render(<UpdatesSection />)
    expect((await screen.findAllByText('Version 0.3.0 is out.')).length).toBeGreaterThan(0)
    expect(screen.getByRole('link', { name: /Release notes/ })).toHaveAttribute(
      'href',
      `${RELEASES}/tag/v0.3.0`,
    )
    const upgrade = screen.getByRole('link', { name: /How to upgrade/ })
    expect(upgrade.getAttribute('href')).toMatch(/\/deploy\/server#updating$/)
    expect(upgrade).toHaveAttribute('rel', 'noopener noreferrer')
  })

  it('only ever links to our releases', async () => {
    getUpdates.mockResolvedValue({ ...SERVER_AVAILABLE, release_url: 'https://evil.example/x' })
    render(<UpdatesSection />)
    expect(await screen.findByRole('link', { name: /Release notes/ })).toHaveAttribute(
      'href',
      RELEASES,
    )
  })

  it.each([
    ['disabled', 'Update checks are turned off on this server.'],
    ['pending', 'Not checked yet.'],
    ['unknown', 'Not a release build.'],
  ] as const)('says when the status is %s', async (status, text) => {
    getUpdates.mockResolvedValue({ ...SERVER, status, latest_version: null })
    render(<UpdatesSection />)
    expect((await screen.findAllByText(text)).length).toBeGreaterThan(0)
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
  })
})

describe('UpdateNotifier', () => {
  it('announces a ready update once per version', async () => {
    const { push } = installUpdateApi(BASE)
    render(<UpdateNotifier />)
    await waitFor(() => expect(window.electronAPI!.getUpdateState).toHaveBeenCalled())

    push({ ...BASE, status: 'ready', version: '0.2.0' })
    push({ ...BASE, status: 'ready', version: '0.2.0', percent: 100 })
    expect(toastInfo).toHaveBeenCalledTimes(1)
    expect(toastInfo).toHaveBeenCalledWith(
      'Scene Atlas 0.2.0 is ready',
      expect.objectContaining({ action: expect.objectContaining({ label: 'Restart' }) }),
    )
  })

  it('announces a new version with a download link in notify mode', async () => {
    installUpdateApi({ ...BASE, mode: 'notify', status: 'available', version: '0.3.0' })
    render(<UpdateNotifier />)
    await waitFor(() =>
      expect(toastInfo).toHaveBeenCalledWith(
        'Scene Atlas 0.3.0 is out',
        expect.objectContaining({ action: expect.objectContaining({ label: 'Download' }) }),
      ),
    )
  })

  it('stays quiet while checking or up to date', async () => {
    const { push } = installUpdateApi(BASE)
    render(<UpdateNotifier />)
    push({ ...BASE, status: 'checking' })
    push({ ...BASE, status: 'downloading', version: '0.2.0', percent: 10 })
    expect(toastInfo).not.toHaveBeenCalled()
  })
})

describe('UpdateNotifier on a server', () => {
  it('announces a new version once per browser, linking to its release notes', async () => {
    getUpdates.mockResolvedValue(SERVER_AVAILABLE)
    const open = vi.spyOn(window, 'open').mockImplementation(() => null)
    const first = render(<UpdateNotifier />)
    await waitFor(() => expect(toastInfo).toHaveBeenCalledTimes(1))
    expect(toastInfo).toHaveBeenCalledWith(
      'Scene Atlas 0.3.0 is out',
      expect.objectContaining({ action: expect.objectContaining({ label: 'Release notes' }) }),
    )
    toastInfo.mock.calls[0][1].action.onClick()
    expect(open).toHaveBeenCalledWith(`${RELEASES}/tag/v0.3.0`, '_blank', 'noopener,noreferrer')
    first.unmount()

    // A reload doesn't repeat it
    render(<UpdateNotifier />)
    await waitFor(() => expect(getUpdates).toHaveBeenCalledTimes(2))
    expect(toastInfo).toHaveBeenCalledTimes(1)
    open.mockRestore()
  })

  it('stays quiet when up to date or checks are off', async () => {
    getUpdates.mockResolvedValue({ ...SERVER, status: 'disabled', checks_enabled: false })
    render(<UpdateNotifier />)
    await waitFor(() => expect(getUpdates).toHaveBeenCalled())
    expect(toastInfo).not.toHaveBeenCalled()
  })
})
