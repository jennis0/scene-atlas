import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook } from '@testing-library/react'
import { libraryApi, type LibraryStatus } from '@/lib/api/libraryApi'
import { FOCUS_RESCAN_INTERVAL_MS, useLinkedFocusRescan } from './useLinkedFocusRescan'

const mode = vi.hoisted(() => ({ isApp: true }))
vi.mock('@/lib/appMode', () => ({
  get isApp() {
    return mode.isApp
  },
}))
vi.mock('@/lib/api/libraryApi', () => ({ libraryApi: { scan: vi.fn() } }))
const refresh = vi.hoisted(() => vi.fn())
vi.mock('@/lib/import/ImportManager', () => ({ getImportManager: () => ({ refresh }) }))

const scan = vi.mocked(libraryApi.scan)

function status(state: 'online' | 'offline' | 'detached' | null): LibraryStatus {
  return {
    library_id: 'lib',
    linked: state && {
      state,
      name: 'Battle Maps',
      path: 'D:\\Battle Maps',
      image_count: 10,
      missing_count: 0,
      last_scan_at: null,
      scanning: false,
    },
  }
}

const focus = () => window.dispatchEvent(new Event('focus'))

describe('useLinkedFocusRescan', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mode.isApp = true
    scan.mockResolvedValue({ started: false })
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-10-19T12:00:00Z'))
  })
  afterEach(() => vi.useRealTimers())

  it('checks the folder on focus, at most once a minute', () => {
    renderHook(() => useLinkedFocusRescan(status('online')))
    focus()
    expect(scan).toHaveBeenCalledWith('focus')
    vi.setSystemTime(Date.now() + FOCUS_RESCAN_INTERVAL_MS - 1)
    focus()
    expect(scan).toHaveBeenCalledTimes(1)
    vi.setSystemTime(Date.now() + 1)
    focus()
    expect(scan).toHaveBeenCalledTimes(2)
  })

  it('picks up the import a scan started', async () => {
    scan.mockResolvedValue({ started: true })
    renderHook(() => useLinkedFocusRescan(status('online')))
    focus()
    await vi.waitFor(() => expect(refresh).toHaveBeenCalled())
  })

  it.each([['offline'], ['detached'], [null]] as const)('leaves a %s folder alone', (state) => {
    renderHook(() => useLinkedFocusRescan(status(state)))
    focus()
    expect(scan).not.toHaveBeenCalled()
  })

  it('is for the desktop app only', () => {
    mode.isApp = false
    renderHook(() => useLinkedFocusRescan(status('online')))
    focus()
    expect(scan).not.toHaveBeenCalled()
  })
})
