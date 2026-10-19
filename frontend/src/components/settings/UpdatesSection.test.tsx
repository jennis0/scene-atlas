import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { AppUpdateState } from '@/electron'
import { UpdatesSection } from './UpdatesSection'
import { UpdateNotifier } from '@/components/UpdateNotifier'

const toastInfo = vi.hoisted(() => vi.fn())
vi.mock('sonner', () => ({ toast: { info: toastInfo } }))

const BASE: AppUpdateState = {
  status: 'up-to-date',
  mode: 'install',
  currentVersion: '0.1.0',
  checksEnabled: true,
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
})

describe('UpdatesSection', () => {
  it('renders nothing outside the desktop app or in a dev build', async () => {
    const { container, unmount } = render(<UpdatesSection />)
    expect(container).toBeEmptyDOMElement()
    unmount()

    installUpdateApi({ ...BASE, status: 'unsupported' })
    const dev = render(<UpdatesSection />)
    await waitFor(() => expect(window.electronAPI!.getUpdateState).toHaveBeenCalled())
    expect(dev.container).toBeEmptyDOMElement()
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
