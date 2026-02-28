import { describe, it, expect } from 'vitest'
import { Leaf, Tag, Sword, Star } from 'lucide-react'
import { getCategoryIcon, CATEGORY_ICON_MAP, CATEGORY_ICON_NAMES } from './categoryIcons'

describe('getCategoryIcon', () => {
  it('returns correct icon for known name', () => {
    expect(getCategoryIcon('leaf')).toBe(Leaf)
    expect(getCategoryIcon('sword')).toBe(Sword)
    expect(getCategoryIcon('star')).toBe(Star)
  })

  it('returns Tag fallback for unknown name', () => {
    expect(getCategoryIcon('nonexistent')).toBe(Tag)
  })

  it('returns Tag fallback for null', () => {
    expect(getCategoryIcon(null)).toBe(Tag)
  })

  it('returns Tag fallback for undefined', () => {
    expect(getCategoryIcon(undefined)).toBe(Tag)
  })
})

describe('CATEGORY_ICON_MAP', () => {
  it('CATEGORY_ICON_NAMES matches map keys', () => {
    expect(CATEGORY_ICON_NAMES).toEqual(Object.keys(CATEGORY_ICON_MAP))
  })

  it('contains expected icons', () => {
    expect(CATEGORY_ICON_MAP).toHaveProperty('leaf')
    expect(CATEGORY_ICON_MAP).toHaveProperty('sword')
    expect(CATEGORY_ICON_MAP).toHaveProperty('mountain')
    expect(CATEGORY_ICON_MAP).toHaveProperty('tag')
  })
})
