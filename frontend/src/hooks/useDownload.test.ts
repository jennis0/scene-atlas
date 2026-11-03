import { describe, it, expect, vi, beforeEach } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import { toast } from 'sonner'
import { downloadsApi } from '@/lib/api/downloadsApi'
import { postForDownload } from '@/lib/download'
import { useDownload } from './useDownload'

vi.mock('@/lib/api/downloadsApi', () => ({ downloadsApi: { check: vi.fn() } }))
vi.mock('@/lib/download', () => ({ postForDownload: vi.fn() }))
vi.mock('sonner', () => ({ toast: { error: vi.fn() } }))

describe('useDownload', () => {
  beforeEach(() => vi.clearAllMocks())

  it('checks, then posts the selection', async () => {
    vi.mocked(downloadsApi.check).mockResolvedValue({
      image_count: 3,
      bytes: 9,
      ok: true,
      reason: null,
    })
    const { result } = renderHook(() => useDownload())
    await act(() => result.current.download({ group_ids: [4, 5], image_ids: [9] }, 'Failed'))
    expect(postForDownload).toHaveBeenCalledWith('/api/v1/downloads', {
      group_ids: '4,5',
      image_ids: '9',
    })
    expect(result.current.busy).toBe(false)
  })

  it('shows the reason a download is refused, and posts nothing', async () => {
    vi.mocked(downloadsApi.check).mockResolvedValue({
      image_count: 0,
      bytes: 0,
      ok: false,
      reason: 'Nothing to download',
    })
    const { result } = renderHook(() => useDownload())
    await act(() => result.current.download({ group_ids: [4] }, 'Failed'))
    expect(toast.error).toHaveBeenCalledWith('Nothing to download')
    expect(postForDownload).not.toHaveBeenCalled()
  })

  it('shows a failure when the check fails', async () => {
    vi.mocked(downloadsApi.check).mockRejectedValue(new Error('network'))
    const { result } = renderHook(() => useDownload())
    await act(() => result.current.download({ group_ids: [4] }, 'Group download failed'))
    expect(toast.error).toHaveBeenCalled()
    expect(postForDownload).not.toHaveBeenCalled()
  })
})
