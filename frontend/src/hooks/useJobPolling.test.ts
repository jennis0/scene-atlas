import { describe, it, expect, vi, afterEach } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import { useJobPolling } from './useJobPolling'

// ── Mock the API ────────────────────────────────────────────────────────────

const mockGet = vi.fn()

vi.mock('@/lib/api', () => ({
  jobApi: {
    get: (...args: unknown[]) => mockGet(...args),
  },
}))

// ── Tests ───────────────────────────────────────────────────────────────────

describe('useJobPolling', () => {
  afterEach(() => {
    vi.clearAllMocks()
  })

  it('does not poll when no job is tracked', async () => {
    const { result } = renderHook(() => useJobPolling())

    expect(result.current.status).toBeNull()
    expect(result.current.isRunning).toBe(false)

    // Wait a tick to ensure no API calls happen
    await new Promise((r) => setTimeout(r, 50))
    expect(mockGet).not.toHaveBeenCalled()
  })

  it('polls and returns running status', async () => {
    mockGet.mockResolvedValue({
      id: 'job-1',
      name: 'Test Job',
      status: 'running',
      progress: 'Step 1 of 3',
      progress_pct: 33,
      error: null,
    })

    const { result } = renderHook(() => useJobPolling({ intervalMs: 50 }))

    act(() => {
      result.current.track('job-1')
    })

    await waitFor(() => {
      expect(result.current.isRunning).toBe(true)
    })

    expect(result.current.status).toBe('running')
    expect(result.current.progress).toBe('Step 1 of 3')
    expect(result.current.progressPct).toBe(33)
    expect(mockGet).toHaveBeenCalledWith('job-1')
  })

  it('stops polling when job completes', async () => {
    let callCount = 0
    mockGet.mockImplementation(() => {
      callCount++
      if (callCount <= 1) {
        return Promise.resolve({
          id: 'job-2',
          name: 'Test',
          status: 'running',
          progress: null,
          progress_pct: null,
          error: null,
        })
      }
      return Promise.resolve({
        id: 'job-2',
        name: 'Test',
        status: 'completed',
        progress: null,
        progress_pct: 100,
        error: null,
      })
    })

    const { result } = renderHook(() => useJobPolling({ intervalMs: 50 }))

    act(() => {
      result.current.track('job-2')
    })

    await waitFor(() => {
      expect(result.current.isComplete).toBe(true)
    })

    expect(result.current.status).toBe('completed')
    expect(result.current.isRunning).toBe(false)

    // Record how many calls, then wait to confirm no more happen
    const finalCount = callCount
    await new Promise((r) => setTimeout(r, 150))
    expect(callCount).toBe(finalCount)
  })

  it('stops polling when job fails', async () => {
    mockGet.mockResolvedValue({
      id: 'job-3',
      name: 'Test',
      status: 'failed',
      progress: null,
      progress_pct: null,
      error: 'Something went wrong',
    })

    const { result } = renderHook(() => useJobPolling({ intervalMs: 50 }))

    act(() => {
      result.current.track('job-3')
    })

    await waitFor(() => {
      expect(result.current.isFailed).toBe(true)
    })

    expect(result.current.error).toBe('Something went wrong')
    expect(result.current.isRunning).toBe(false)
  })

  it('reset clears state and stops polling', async () => {
    mockGet.mockResolvedValue({
      id: 'job-4',
      name: 'Test',
      status: 'running',
      progress: null,
      progress_pct: null,
      error: null,
    })

    const { result } = renderHook(() => useJobPolling({ intervalMs: 50 }))

    act(() => {
      result.current.track('job-4')
    })

    await waitFor(() => {
      expect(result.current.isRunning).toBe(true)
    })

    act(() => {
      result.current.reset()
    })

    expect(result.current.status).toBeNull()
    expect(result.current.isRunning).toBe(false)
  })
})
