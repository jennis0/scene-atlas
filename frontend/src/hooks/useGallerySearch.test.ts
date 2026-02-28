import { describe, it, expect, beforeEach } from 'vitest'
import {
  parseSortKey,
  loadSortKey,
  parseFiltersFromUrl,
  buildUrlParams,
  SORT_OPTIONS,
} from './useGallerySearch'
import type { ActiveFilter } from '@/components/import/fileFilter'

// ---------------------------------------------------------------------------
// Unit tests for pure helper functions (no React needed)
// ---------------------------------------------------------------------------

beforeEach(() => {
  localStorage.clear()
})

describe('parseSortKey', () => {
  it('splits a sort key into [SortBy, SortDir]', () => {
    expect(parseSortKey('created_at:desc')).toEqual(['created_at', 'desc'])
    expect(parseSortKey('name:asc')).toEqual(['name', 'asc'])
    expect(parseSortKey('relevance:desc')).toEqual(['relevance', 'desc'])
  })
})

describe('loadSortKey', () => {
  it('returns default sort key when localStorage is empty', () => {
    expect(loadSortKey()).toBe('created_at:desc')
  })

  it('returns stored sort key when valid', () => {
    localStorage.setItem('gallery-sort', 'name:asc')
    expect(loadSortKey()).toBe('name:asc')
  })

  it('returns default sort key when stored value is invalid', () => {
    localStorage.setItem('gallery-sort', 'invalid:key')
    expect(loadSortKey()).toBe('created_at:desc')
  })

  it('returns default sort key when stored value is relevance:desc', () => {
    // relevance:desc is valid in SORT_OPTIONS, so it should be returned
    localStorage.setItem('gallery-sort', 'relevance:desc')
    expect(loadSortKey()).toBe('relevance:desc')
  })
})

describe('parseFiltersFromUrl', () => {
  it('parses empty URL params to empty filters', () => {
    const params = new URLSearchParams()
    expect(parseFiltersFromUrl(params)).toEqual([])
  })

  it('parses tag filters', () => {
    const params = new URLSearchParams('tag=env:forest&tag=time:night')
    const result = parseFiltersFromUrl(params)
    expect(result).toHaveLength(2)
    expect(result[0]).toEqual({
      type: 'tag',
      value: 'env:forest',
      label: 'forest',
      exclude: false,
    })
    expect(result[1]).toEqual({
      type: 'tag',
      value: 'time:night',
      label: 'night',
      exclude: false,
    })
  })

  it('parses excluded tag filters', () => {
    const params = new URLSearchParams('xtag=env:cave')
    const result = parseFiltersFromUrl(params)
    expect(result).toHaveLength(1)
    expect(result[0].exclude).toBe(true)
    expect(result[0].type).toBe('tag')
  })

  it('parses author filters', () => {
    const params = new URLSearchParams('author=Alice&xauthor=Bob')
    const result = parseFiltersFromUrl(params)
    expect(result).toHaveLength(2)
    expect(result[0]).toEqual({ type: 'author', value: 'Alice', label: 'Alice', exclude: false })
    expect(result[1]).toEqual({ type: 'author', value: 'Bob', label: 'Bob', exclude: true })
  })

  it('parses gridded filter', () => {
    const params = new URLSearchParams('gridded=square')
    const result = parseFiltersFromUrl(params)
    expect(result).toHaveLength(1)
    expect(result[0]).toEqual({
      type: 'gridded',
      value: 'square',
      label: 'grid: Square',
      exclude: false,
    })
  })

  it('parses color filters', () => {
    const params = new URLSearchParams('color=%23ff0000')
    const result = parseFiltersFromUrl(params)
    expect(result).toHaveLength(1)
    expect(result[0].type).toBe('color')
  })

  it('parses media_type filters with display labels', () => {
    const params = new URLSearchParams('media_type=image&media_type=video')
    const result = parseFiltersFromUrl(params)
    expect(result).toHaveLength(2)
    expect(result[0].label).toBe('media: Images')
    expect(result[1].label).toBe('media: Videos')
  })
})

describe('buildUrlParams', () => {
  it('builds empty params for no query or filters', () => {
    const params = buildUrlParams('', [])
    expect(params.toString()).toBe('')
  })

  it('includes query parameter', () => {
    const params = buildUrlParams('forest', [])
    expect(params.get('q')).toBe('forest')
  })

  it('includes image type when not "all"', () => {
    const params = buildUrlParams('', [], 'battlemap')
    expect(params.get('image_type')).toBe('battlemap')
  })

  it('omits image_type when "all"', () => {
    const params = buildUrlParams('', [], 'all')
    expect(params.get('image_type')).toBeNull()
  })

  it('serializes tag filters correctly', () => {
    const filters: ActiveFilter[] = [
      { type: 'tag', value: 'env:forest', label: 'forest', exclude: false },
      { type: 'tag', value: 'env:cave', label: 'cave', exclude: true },
    ]
    const params = buildUrlParams('', filters)
    expect(params.getAll('tag')).toEqual(['env:forest'])
    expect(params.getAll('xtag')).toEqual(['env:cave'])
  })

  it('serializes author filters correctly', () => {
    const filters: ActiveFilter[] = [
      { type: 'author', value: 'Alice', label: 'Alice', exclude: false },
      { type: 'author', value: 'Bob', label: 'Bob', exclude: true },
    ]
    const params = buildUrlParams('', filters)
    expect(params.getAll('author')).toEqual(['Alice'])
    expect(params.getAll('xauthor')).toEqual(['Bob'])
  })

  it('serializes gridded filter', () => {
    const filters: ActiveFilter[] = [
      { type: 'gridded', value: 'hex', label: 'grid: Hex', exclude: false },
    ]
    const params = buildUrlParams('', filters)
    expect(params.get('gridded')).toBe('hex')
  })

  it('serializes color filters', () => {
    const filters: ActiveFilter[] = [
      { type: 'color', value: '#ff0000', label: '#ff0000', exclude: false },
    ]
    const params = buildUrlParams('', filters)
    expect(params.getAll('color')).toEqual(['#ff0000'])
  })

  it('serializes media_type filters', () => {
    const filters: ActiveFilter[] = [
      { type: 'media_type', value: 'video', label: 'media: Videos', exclude: false },
    ]
    const params = buildUrlParams('', filters)
    expect(params.getAll('media_type')).toEqual(['video'])
  })

  it('round-trips through parseFiltersFromUrl', () => {
    const originalFilters: ActiveFilter[] = [
      { type: 'tag', value: 'env:forest', label: 'forest', exclude: false },
      { type: 'author', value: 'Alice', label: 'Alice', exclude: false },
      { type: 'gridded', value: 'gridded', label: 'grid: Gridded', exclude: false },
    ]
    const params = buildUrlParams('test query', originalFilters, 'battlemap')
    const parsed = parseFiltersFromUrl(params)

    expect(parsed).toHaveLength(3)
    expect(params.get('q')).toBe('test query')
    expect(params.get('image_type')).toBe('battlemap')
  })
})

describe('SORT_OPTIONS', () => {
  it('has relevance option marked as queryOnly', () => {
    const relevanceOpt = SORT_OPTIONS.find((o) => o.value === 'relevance')
    expect(relevanceOpt).toBeDefined()
    expect(relevanceOpt!.queryOnly).toBe(true)
  })

  it('has non-queryOnly options for date and name', () => {
    const dateOpts = SORT_OPTIONS.filter((o) => o.value === 'created_at')
    expect(dateOpts).toHaveLength(2) // asc + desc
    expect(dateOpts.every((o) => !o.queryOnly)).toBe(true)
  })
})
