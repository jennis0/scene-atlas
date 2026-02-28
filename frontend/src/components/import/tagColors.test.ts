import { describe, it, expect } from 'vitest'
import { getTagColor, DEFAULT_TAG_COLOR, COLOR_PALETTE } from './tagColors'

describe('getTagColor', () => {
  it('returns correct TagColor for a known color name', () => {
    const result = getTagColor('red')
    expect(result).toBe(COLOR_PALETTE['red'])
    expect(result.bg).toBe('bg-red-400/10')
    expect(result.text).toBe('text-red-300')
    expect(result.border).toBe('border-red-400/30')
    expect(result.dot).toBe('bg-red-400')
  })

  it('is case-insensitive', () => {
    expect(getTagColor('Red')).toBe(COLOR_PALETTE['red'])
    expect(getTagColor('AMBER')).toBe(COLOR_PALETTE['amber'])
  })

  it('returns DEFAULT_TAG_COLOR for null', () => {
    expect(getTagColor(null)).toBe(DEFAULT_TAG_COLOR)
  })

  it('returns DEFAULT_TAG_COLOR for undefined', () => {
    expect(getTagColor(undefined)).toBe(DEFAULT_TAG_COLOR)
  })

  it('returns DEFAULT_TAG_COLOR for unknown color name', () => {
    expect(getTagColor('nonexistent')).toBe(DEFAULT_TAG_COLOR)
  })

  it('palette entries have all four fields', () => {
    for (const [name, color] of Object.entries(COLOR_PALETTE)) {
      expect(color, `${name} missing bg`).toHaveProperty('bg')
      expect(color, `${name} missing text`).toHaveProperty('text')
      expect(color, `${name} missing border`).toHaveProperty('border')
      expect(color, `${name} missing dot`).toHaveProperty('dot')
    }
  })
})
