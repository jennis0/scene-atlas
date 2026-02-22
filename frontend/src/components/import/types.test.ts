import { describe, it, expect } from 'vitest'
import { parseTagVocabulary, humanizeFilename } from './types'
import type { TagCategory } from '@/types'

// ── parseTagVocabulary ────────────────────────────────────────────────────────

describe('parseTagVocabulary', () => {
  function makeCategory(overrides: Partial<TagCategory>): TagCategory {
    return {
      id: 1,
      name: 'environment',
      description: null,
      color: null,
      display_order: 0,
      common_values: null,
      ...overrides,
    }
  }

  it('returns empty array when categories is empty', () => {
    expect(parseTagVocabulary([])).toEqual([])
  })

  it('parses string-array JSON common_values', () => {
    const cat = makeCategory({
      name: 'environment',
      common_values: JSON.stringify(['forest', 'dungeon', 'cave']),
    })
    expect(parseTagVocabulary([cat])).toEqual([
      { category: 'environment', values: ['forest', 'dungeon', 'cave'], aliases: {} },
    ])
  })

  it('parses object-array JSON common_values (extracts .value field)', () => {
    const cat = makeCategory({
      name: 'lighting',
      common_values: JSON.stringify([
        { value: 'daylight', count: 10 },
        { value: 'night', count: 5 },
      ]),
    })
    expect(parseTagVocabulary([cat])).toEqual([
      { category: 'lighting', values: ['daylight', 'night'], aliases: {} },
    ])
  })

  it('filters out categories with null common_values', () => {
    const cat = makeCategory({ name: 'empty', common_values: null })
    expect(parseTagVocabulary([cat])).toEqual([])
  })

  it('filters out categories with empty common_values array', () => {
    const cat = makeCategory({ name: 'empty', common_values: JSON.stringify([]) })
    expect(parseTagVocabulary([cat])).toEqual([])
  })

  it('silently skips categories with malformed JSON', () => {
    const cat = makeCategory({ name: 'broken', common_values: 'not valid json' })
    expect(parseTagVocabulary([cat])).toEqual([])
  })

  it('processes multiple categories correctly', () => {
    const cats: TagCategory[] = [
      makeCategory({ id: 1, name: 'environment', common_values: JSON.stringify(['forest']) }),
      makeCategory({ id: 2, name: 'lighting', common_values: null }),
      makeCategory({ id: 3, name: 'season', common_values: JSON.stringify(['summer', 'winter']) }),
    ]
    expect(parseTagVocabulary(cats)).toEqual([
      { category: 'environment', values: ['forest'], aliases: {} },
      { category: 'season', values: ['summer', 'winter'], aliases: {} },
    ])
  })

  it('handles mixed string and object entries in the same array', () => {
    const cat = makeCategory({
      name: 'mixed',
      common_values: JSON.stringify(['plain', { value: 'object-style' }]),
    })
    expect(parseTagVocabulary([cat])).toEqual([
      { category: 'mixed', values: ['plain', 'object-style'], aliases: {} },
    ])
  })

  it('extracts aliases from object entries', () => {
    const cat = makeCategory({
      name: 'environment',
      common_values: JSON.stringify([
        { value: 'forest', aliases: ['woods', 'woodland'] },
        { value: 'cave' },
        'dungeon',
      ]),
    })
    expect(parseTagVocabulary([cat])).toEqual([
      {
        category: 'environment',
        values: ['forest', 'cave', 'dungeon'],
        aliases: { forest: ['woods', 'woodland'] },
      },
    ])
  })
})

// ── humanizeFilename ──────────────────────────────────────────────────────────

describe('humanizeFilename', () => {
  it('strips file extension', () => {
    expect(humanizeFilename('forest.jpg')).toBe('forest')
  })

  it('strips multi-part extension', () => {
    expect(humanizeFilename('map.final.png')).toBe('map.final')
  })

  it('replaces underscores with spaces', () => {
    expect(humanizeFilename('dark_forest_map.jpg')).toBe('dark forest map')
  })

  it('replaces dashes with spaces', () => {
    expect(humanizeFilename('dark-forest-map.jpg')).toBe('dark forest map')
  })

  it('replaces mixed underscores and dashes with spaces', () => {
    expect(humanizeFilename('dark_forest-map.jpg')).toBe('dark forest map')
  })

  it('collapses multiple consecutive separators', () => {
    expect(humanizeFilename('dark__forest--map.jpg')).toBe('dark forest map')
  })

  it('trims leading and trailing whitespace', () => {
    expect(humanizeFilename('_map_.jpg')).toBe('map')
  })

  it('handles filename with no extension', () => {
    expect(humanizeFilename('battlemap')).toBe('battlemap')
  })

  it('handles filename with no separators', () => {
    expect(humanizeFilename('MyMap.png')).toBe('MyMap')
  })

  it('handles empty string', () => {
    expect(humanizeFilename('')).toBe('')
  })
})
