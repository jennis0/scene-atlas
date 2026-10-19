import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// zoom.ts caches the level, so each test loads a fresh copy.
async function loadZoom() {
  vi.resetModules()
  return import('./zoom')
}

function installDesktop(platform = 'win32') {
  const api = {
    platform,
    displayPrefs: {},
    setDisplayPref: vi.fn().mockResolvedValue(undefined),
    setZoom: vi.fn(),
  }
  ;(window as { electronAPI?: unknown }).electronAPI = api
  return api
}

function press(key: string, modifiers: Partial<KeyboardEventInit> = { ctrlKey: true }) {
  const event = new KeyboardEvent('keydown', { key, cancelable: true, ...modifiers })
  window.dispatchEvent(event)
  return event
}

describe('zoom', () => {
  beforeEach(() => localStorage.clear())
  afterEach(() => {
    delete (window as { electronAPI?: unknown }).electronAPI
  })

  it('steps through the levels, stops at the ends, and resets to 100%', async () => {
    const { nextZoom } = await loadZoom()
    expect(nextZoom(100, 1)).toBe(110)
    expect(nextZoom(110, 1)).toBe(125)
    expect(nextZoom(100, -1)).toBe(90)
    expect(nextZoom(200, 1)).toBe(200)
    expect(nextZoom(80, -1)).toBe(80)
    expect(nextZoom(175, 0)).toBe(100)
  })

  it('reads the saved level, and 100% for anything that is not a level', async () => {
    localStorage.setItem('scene-atlas-zoom', '150')
    expect((await loadZoom()).getZoom()).toBe(150)
    for (const saved of ['137', 'big', '']) {
      localStorage.setItem('scene-atlas-zoom', saved)
      expect((await loadZoom()).getZoom()).toBe(100)
    }
  })

  it('saves a new level on this device and in the desktop config, and applies it', async () => {
    const api = installDesktop()
    const { getZoom, setZoom } = await loadZoom()
    setZoom(125)
    expect(getZoom()).toBe(125)
    expect(localStorage.getItem('scene-atlas-zoom')).toBe('125')
    expect(api.setDisplayPref).toHaveBeenCalledWith('scene-atlas-zoom', '125')
    expect(api.setZoom).toHaveBeenCalledWith(125)
  })

  it('maps the shortcuts, with Cmd on macOS and Ctrl elsewhere', async () => {
    const { zoomStepForKey } = await loadZoom()
    const key = (k: string, mods: Partial<KeyboardEvent> = {}) => ({
      key: k,
      ctrlKey: false,
      metaKey: false,
      altKey: false,
      ...mods,
    })
    expect(zoomStepForKey(key('=', { ctrlKey: true }), false)).toBe(1)
    expect(zoomStepForKey(key('+', { ctrlKey: true }), false)).toBe(1)
    expect(zoomStepForKey(key('-', { ctrlKey: true }), false)).toBe(-1)
    expect(zoomStepForKey(key('_', { ctrlKey: true }), false)).toBe(-1)
    expect(zoomStepForKey(key('0', { ctrlKey: true }), false)).toBe(0)
    expect(zoomStepForKey(key('=', { metaKey: true }), true)).toBe(1)
    // Not without the modifier, with Alt, with the other platform's modifier, or other keys
    expect(zoomStepForKey(key('='), false)).toBeNull()
    expect(zoomStepForKey(key('=', { ctrlKey: true, altKey: true }), false)).toBeNull()
    expect(zoomStepForKey(key('=', { ctrlKey: true }), true)).toBeNull()
    expect(zoomStepForKey(key('1', { ctrlKey: true }), false)).toBeNull()
  })

  it('zooms on the shortcuts until unsubscribed, and keeps them from the page', async () => {
    const api = installDesktop()
    const { getZoom, listenForZoomKeys } = await loadZoom()
    const stop = listenForZoomKeys()
    expect(press('=').defaultPrevented).toBe(true)
    press('=')
    expect(getZoom()).toBe(125)
    expect(api.setZoom).toHaveBeenLastCalledWith(125)
    press('0')
    expect(getZoom()).toBe(100)
    expect(press('a').defaultPrevented).toBe(false)
    stop()
    press('=')
    expect(getZoom()).toBe(100)
  })

  it('leaves the shortcuts to the browser', async () => {
    const { getZoom, listenForZoomKeys } = await loadZoom()
    const stop = listenForZoomKeys()
    expect(press('=').defaultPrevented).toBe(false)
    expect(getZoom()).toBe(100)
    stop()
  })
})
