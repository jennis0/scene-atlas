import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { readPref, registerPref, syncPrefsWithDesktop, writePref } from './prefsStorage'

const KEY = 'scene-atlas-test-pref'
const OTHER = 'scene-atlas-test-other'
registerPref(KEY)
registerPref(OTHER)

function installDesktop(displayPrefs: Record<string, string>) {
  const setDisplayPref = vi.fn().mockResolvedValue(undefined)
  ;(window as { electronAPI?: unknown }).electronAPI = { displayPrefs, setDisplayPref }
  return setDisplayPref
}

describe('prefsStorage', () => {
  beforeEach(() => localStorage.clear())
  afterEach(() => {
    delete (window as { electronAPI?: unknown }).electronAPI
    vi.restoreAllMocks()
  })

  describe('in the browser', () => {
    it('reads and writes localStorage', () => {
      expect(readPref(KEY)).toBeNull()
      writePref(KEY, 'dark')
      expect(localStorage.getItem(KEY)).toBe('dark')
      expect(readPref(KEY)).toBe('dark')
    })

    it('does nothing at sync time', () => {
      localStorage.setItem(KEY, 'dark')
      syncPrefsWithDesktop()
      expect(localStorage.getItem(KEY)).toBe('dark')
    })
  })

  describe('in the desktop app', () => {
    it("lets the config's values replace this origin's localStorage", () => {
      localStorage.setItem(KEY, 'stale')
      const setDisplayPref = installDesktop({ [KEY]: 'lapis' })
      syncPrefsWithDesktop()
      expect(readPref(KEY)).toBe('lapis')
      expect(setDisplayPref).not.toHaveBeenCalledWith(KEY, expect.anything())
    })

    it('copies values only localStorage has into the config, once', () => {
      localStorage.setItem(OTHER, 'large')
      const setDisplayPref = installDesktop({ [KEY]: 'lapis' })
      syncPrefsWithDesktop()
      expect(setDisplayPref).toHaveBeenCalledWith(OTHER, 'large')
      expect(setDisplayPref).toHaveBeenCalledTimes(1)
    })

    it('keeps a new port working: an empty localStorage gets the saved values', () => {
      installDesktop({ [KEY]: 'dark' })
      syncPrefsWithDesktop()
      expect(localStorage.getItem(KEY)).toBe('dark')
    })

    it('writes to both, and later reads see the change', () => {
      const setDisplayPref = installDesktop({ [KEY]: 'dark' })
      syncPrefsWithDesktop()
      writePref(KEY, 'light')
      expect(setDisplayPref).toHaveBeenCalledWith(KEY, 'light')
      expect(readPref(KEY)).toBe('light')
    })

    it('falls back to the config copy when localStorage is blocked', () => {
      installDesktop({ [KEY]: 'dark' })
      vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
        throw new Error('SecurityError')
      })
      expect(readPref(KEY)).toBe('dark')
    })
  })
})
