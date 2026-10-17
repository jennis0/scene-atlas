import { describe, it, expect } from 'vitest'
import { getTagColor, getDotColor, DEFAULT_TAG_COLOR, PALETTE_KEYS } from './tagColors'

describe('getTagColor', () => {
  describe('dark mode (default)', () => {
    it('returns correct dark TagColor for a known color name', () => {
      const result = getTagColor('red')
      expect(result.bg).toBe('bg-red-400/10')
      expect(result.text).toBe('text-red-300')
      expect(result.border).toBe('border-red-400/30')
      expect(result.dot).toBe('bg-red-400')
    })

    it('is case-insensitive', () => {
      expect(getTagColor('Red')).toEqual(getTagColor('red'))
      expect(getTagColor('AMBER')).toEqual(getTagColor('amber'))
    })

    it('returns DEFAULT_TAG_COLOR for null', () => {
      expect(getTagColor(null)).toEqual(DEFAULT_TAG_COLOR)
    })

    it('returns DEFAULT_TAG_COLOR for undefined', () => {
      expect(getTagColor(undefined)).toEqual(DEFAULT_TAG_COLOR)
    })

    it('returns DEFAULT_TAG_COLOR for unknown color name', () => {
      expect(getTagColor('nonexistent')).toEqual(DEFAULT_TAG_COLOR)
    })
  })

  describe('light mode', () => {
    it('returns correct light TagColor for a known color name', () => {
      const result = getTagColor('red', 'light')
      expect(result.bg).toBe('bg-red-50')
      expect(result.text).toBe('text-red-800')
      expect(result.border).toBe('border-red-200')
      expect(result.dot).toBe('bg-red-400') // dot is theme-independent
    })

    it('returns light default for null', () => {
      const result = getTagColor(null, 'light')
      expect(result.bg).toBe('bg-zinc-100')
      expect(result.text).toBe('text-zinc-600')
      expect(result.border).toBe('border-zinc-300')
    })

    it('preserves colour identity across themes', () => {
      const dark = getTagColor('teal', 'dark')
      const light = getTagColor('teal', 'light')
      // Same hue (teal), different shades
      expect(dark.text).toContain('teal')
      expect(light.text).toContain('teal')
      // Dot is identical
      expect(dark.dot).toBe(light.dot)
    })
  })

  it('all palette entries return 4 fields in both themes', () => {
    for (const name of PALETTE_KEYS) {
      for (const theme of ['dark', 'light'] as const) {
        const color = getTagColor(name, theme)
        expect(color.bg, `${name}/${theme} missing bg`).toBeTruthy()
        expect(color.text, `${name}/${theme} missing text`).toBeTruthy()
        expect(color.border, `${name}/${theme} missing border`).toBeTruthy()
        expect(color.dot, `${name}/${theme} missing dot`).toBeTruthy()
      }
    }
  })
})

describe('getDotColor', () => {
  it('returns the dot class for a known color', () => {
    expect(getDotColor('red')).toBe('bg-red-400')
  })

  it('returns fallback for unknown color', () => {
    expect(getDotColor('nonexistent')).toBe('bg-zinc-400')
  })
})
