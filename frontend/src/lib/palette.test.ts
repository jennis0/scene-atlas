import { describe, it, expect, beforeEach } from 'vitest'
import { applyPalette, getStoredPalette, PALETTE_STORAGE_KEY } from './palette'

describe('palette', () => {
  beforeEach(() => {
    localStorage.clear()
    delete document.documentElement.dataset.palette
  })

  it('defaults to navy, including for unknown stored values', () => {
    expect(getStoredPalette()).toBe('navy')
    localStorage.setItem(PALETTE_STORAGE_KEY, 'neon')
    expect(getStoredPalette()).toBe('navy')
  })

  it('reads a saved palette', () => {
    localStorage.setItem(PALETTE_STORAGE_KEY, 'verdigris')
    expect(getStoredPalette()).toBe('verdigris')
  })

  it('sets data-palette for non-default palettes and clears it for navy', () => {
    applyPalette('verdigris')
    expect(document.documentElement.dataset.palette).toBe('verdigris')
    applyPalette('navy')
    expect(document.documentElement.dataset.palette).toBeUndefined()
  })
})
