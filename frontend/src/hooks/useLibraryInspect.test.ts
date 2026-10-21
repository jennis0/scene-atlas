import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor, act } from '@testing-library/react'
import type { LibraryDirs } from '@/electron'
import { libraryApi, type InspectResult } from '@/lib/api/libraryApi'
import { useLibraryInspect } from './useLibraryInspect'

vi.mock('@/lib/api/libraryApi', () => ({ libraryApi: { inspect: vi.fn() } }))

const inspect = vi.mocked(libraryApi.inspect)

function result(message: string): InspectResult {
  return {
    outcome: 'new',
    message,
    linked: null,
    library: null,
    store_has_maps: false,
  }
}

function deferred() {
  let resolve!: (r: InspectResult) => void
  const promise = new Promise<InspectResult>((r) => (resolve = r))
  return { promise, resolve }
}

const A: LibraryDirs = { appData: '/a', store: '/a/images', linked: null }
const B: LibraryDirs = { appData: '/b', store: '/b/images', linked: '/maps' }

describe('useLibraryInspect', () => {
  beforeEach(() => vi.clearAllMocks())

  it('does nothing without folders to check', () => {
    const { result: hook } = renderHook(() => useLibraryInspect(null))
    expect(hook.current.state).toEqual({ status: 'idle' })
    expect(inspect).not.toHaveBeenCalled()
  })

  it('sends one request for quick changes', async () => {
    inspect.mockResolvedValue(result('b'))
    const { result: hook, rerender } = renderHook(({ req }) => useLibraryInspect(req), {
      initialProps: { req: A },
    })
    rerender({ req: B })
    await waitFor(() => expect(hook.current.state).toEqual({ status: 'done', result: result('b') }))
    expect(inspect).toHaveBeenCalledTimes(1)
    expect(inspect).toHaveBeenCalledWith({ app_data: '/b', store: '/b/images', linked: '/maps' })
  })

  it('never lets a slow answer for older folders replace a newer one', async () => {
    const slow = deferred()
    const fast = deferred()
    inspect.mockReturnValueOnce(slow.promise).mockReturnValueOnce(fast.promise)
    const { result: hook, rerender } = renderHook(({ req }) => useLibraryInspect(req), {
      initialProps: { req: A },
    })
    await waitFor(() => expect(inspect).toHaveBeenCalledTimes(1))
    rerender({ req: B })
    await waitFor(() => expect(inspect).toHaveBeenCalledTimes(2))
    expect(hook.current.state).toEqual({ status: 'checking' })

    await act(async () => fast.resolve(result('b')))
    await act(async () => slow.resolve(result('a')))
    expect(hook.current.state).toEqual({ status: 'done', result: result('b') })
  })

  it('reports a failure, and checks again on retry', async () => {
    inspect.mockRejectedValueOnce(new Error('offline')).mockResolvedValue(result('ok'))
    const { result: hook } = renderHook(() => useLibraryInspect(A))
    await waitFor(() => expect(hook.current.state).toEqual({ status: 'failed' }))
    act(() => hook.current.retry())
    expect(hook.current.state).toEqual({ status: 'checking' })
    await waitFor(() =>
      expect(hook.current.state).toEqual({ status: 'done', result: result('ok') }),
    )
  })
})
