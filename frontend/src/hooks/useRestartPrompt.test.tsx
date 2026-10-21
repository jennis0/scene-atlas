import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { settingsApi } from '@/lib/api/settingsApi'
import type { AppSettings } from '@/types'
import { useRestartPrompt } from './useRestartPrompt'

vi.mock('@/lib/api/settingsApi', () => ({
  settingsApi: { restartPending: vi.fn() },
}))

const saved = { max_concurrent_prepare: 4 } as AppSettings
const KEY = 'max_concurrent_prepare'

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

function prompt(draft: Partial<AppSettings>, save = vi.fn().mockResolvedValue(undefined)) {
  return renderHook(() => useRestartPrompt({ enabled: true, settings: saved, draft, save }), {
    wrapper,
  })
}

describe('useRestartPrompt', () => {
  beforeEach(() => {
    vi.mocked(settingsApi.restartPending).mockResolvedValue([])
  })
  afterEach(() => {
    delete window.electronAPI
  })

  it('is not pending while the setting is as the backend started with it', async () => {
    const { result } = prompt({})
    await waitFor(() => expect(settingsApi.restartPending).toHaveBeenCalled())
    expect(result.current(KEY).pending).toBe(false)
  })

  it('is pending once the draft changes it, and not when it is changed back', () => {
    expect(prompt({ max_concurrent_prepare: 6 }).result.current(KEY).pending).toBe(true)
    expect(prompt({ max_concurrent_prepare: 4 }).result.current(KEY).pending).toBe(false)
  })

  it('is pending when a saved change has not been applied yet', async () => {
    vi.mocked(settingsApi.restartPending).mockResolvedValue([KEY])
    const { result } = prompt({})
    await waitFor(() => expect(result.current(KEY).pending).toBe(true))
  })

  it('has no restart on a server', () => {
    expect(prompt({ max_concurrent_prepare: 6 }).result.current(KEY).onRestart).toBeUndefined()
  })

  it('saves, then restarts the desktop app backend', async () => {
    const order: string[] = []
    const save = vi.fn(async () => void order.push('save'))
    const restartBackend = vi.fn(() => {
      order.push('restart')
      return new Promise<boolean>(() => {}) // the page reloads
    })
    window.electronAPI = { restartBackend } as unknown as Window['electronAPI']
    const { result } = prompt({ max_concurrent_prepare: 6 }, save)
    act(() => result.current(KEY).onRestart?.())
    await waitFor(() => expect(order).toEqual(['save', 'restart']))
    expect(result.current(KEY).restarting).toBe(true)
  })

  it('stops restarting where the backend cannot be restarted (dev)', async () => {
    window.electronAPI = {
      restartBackend: vi.fn().mockResolvedValue(false),
    } as unknown as Window['electronAPI']
    const { result } = prompt({ max_concurrent_prepare: 6 })
    act(() => result.current(KEY).onRestart?.())
    await waitFor(() => expect(window.electronAPI?.restartBackend).toHaveBeenCalled())
    await waitFor(() => expect(result.current(KEY).restarting).toBe(false))
  })
})
