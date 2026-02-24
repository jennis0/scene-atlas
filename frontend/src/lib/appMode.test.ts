import { describe, it, expect, afterEach, vi } from 'vitest'

describe('appMode', () => {
  afterEach(() => {
    vi.resetModules()
    delete (window as any).electronAPI
  })

  it('returns "server" when electronAPI is absent', async () => {
    delete (window as any).electronAPI
    const { appMode, isApp, isServer } = await import('./appMode')
    expect(appMode).toBe('server')
    expect(isApp).toBe(false)
    expect(isServer).toBe(true)
  })

  it('returns "app" when electronAPI is present', async () => {
    ;(window as any).electronAPI = { onBackendReady: vi.fn() }
    const { appMode, isApp, isServer } = await import('./appMode')
    expect(appMode).toBe('app')
    expect(isApp).toBe(true)
    expect(isServer).toBe(false)
  })

  it('returns "server" when electronAPI is explicitly undefined', async () => {
    ;(window as any).electronAPI = undefined
    const { appMode } = await import('./appMode')
    expect(appMode).toBe('server')
  })
})
