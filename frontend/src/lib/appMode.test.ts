import { describe, it, expect, afterEach, vi } from 'vitest'

describe('appMode', () => {
  afterEach(() => {
    vi.resetModules()
    delete (window as any).electronAPI
  })

  it('returns "server" when electronAPI is absent', async () => {
    delete (window as any).electronAPI
    const { appMode, isApp } = await import('./appMode')
    expect(appMode).toBe('server')
    expect(isApp).toBe(false)
  })

  it('returns "app" when electronAPI is present', async () => {
    ;(window as any).electronAPI = { onBackendError: vi.fn() }
    const { appMode, isApp } = await import('./appMode')
    expect(appMode).toBe('app')
    expect(isApp).toBe(true)
  })

  it.each([
    ['darwin', 'inset', true],
    ['win32', 'overlay', true],
    ['linux', 'native', false],
  ])('on %s the title bar is %s', async (platform, chrome, frameless) => {
    ;(window as any).electronAPI = { platform }
    const { windowChrome, isFrameless } = await import('./appMode')
    expect(windowChrome).toBe(chrome)
    expect(isFrameless).toBe(frameless)
  })

  it('leaves the title bar to the browser', async () => {
    delete (window as any).electronAPI
    const { windowChrome, isFrameless } = await import('./appMode')
    expect(windowChrome).toBe('native')
    expect(isFrameless).toBe(false)
  })

  it('returns "server" when electronAPI is explicitly undefined', async () => {
    ;(window as any).electronAPI = undefined
    const { appMode } = await import('./appMode')
    expect(appMode).toBe('server')
  })
})
