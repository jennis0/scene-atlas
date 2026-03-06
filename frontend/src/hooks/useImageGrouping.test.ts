import { describe, it, expect } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useImageGrouping } from './useImageGrouping'
import type { Image, Tag } from '@/types'

// ── Fixtures ──────────────────────────────────────────────────────────────────

function makeImage(overrides: Partial<Image> = {}): Image {
  return {
    id: 1,
    storage_key: 'key-1',
    filename: 'forest.jpg',
    author: 'Author A',
    name: 'Forest Map',
    group_id: null,
    group_name: null,
    group_image_count: null,
    created_at: '2025-01-15T10:00:00Z',
    updated_at: '2025-01-15T10:00:00Z',
    file_size: 1024,
    width: 1920,
    height: 1080,
    gridded: null,
    grid_width: null,
    grid_height: null,
    grid_type: null,
    grid_confidence: null,
    subgroup: null,
    image_type: 'battlemap',
    thumbnail_key: null,
    media_type: 'image',
    tags: [],
    colors: [],
    ...overrides,
  }
}

function makeTag(category: string, value: string): Tag {
  return { id: 1, image_id: 1, category, value, confidence: 1.0, source: 'manual' }
}

// ── Grouping ──────────────────────────────────────────────────────────────────

describe('useImageGrouping — Grouping', () => {
  it('ungrouped images become single-item groups', () => {
    const images = [makeImage({ id: 1, name: 'A' }), makeImage({ id: 2, name: 'B' })]

    const { result } = renderHook(() => useImageGrouping({ images }))

    expect(result.current).toHaveLength(2)
    expect(result.current[0].groupId).toBeNull()
    expect(result.current[0].heroImage.id).toBe(1)
    expect(result.current[0].mosaicImages).toHaveLength(0)
    expect(result.current[0].matchingCount).toBe(1)
  })

  it('groups images by group_id', () => {
    const images = [
      makeImage({ id: 1, group_id: 100, group_name: 'Forest Pack', name: 'Forest Day' }),
      makeImage({ id: 2, group_id: 100, group_name: 'Forest Pack', name: 'Forest Night' }),
      makeImage({ id: 3, name: 'Standalone' }),
    ]

    const { result } = renderHook(() => useImageGrouping({ images }))

    expect(result.current).toHaveLength(2) // 1 group + 1 standalone
    const group = result.current.find((g) => g.groupId === 100)!
    expect(group.matchingCount).toBe(2)
    expect(group.baseName).toBe('Forest Pack')
  })

  it('hero image is the first image in the group', () => {
    const images = [
      makeImage({ id: 1, group_id: 100, name: 'A' }),
      makeImage({ id: 2, group_id: 100, name: 'B' }),
      makeImage({ id: 3, group_id: 100, name: 'C' }),
    ]

    const { result } = renderHook(() => useImageGrouping({ images }))

    const group = result.current.find((g) => g.groupId === 100)!
    expect(group.heroImage.id).toBe(1)
    expect(group.mosaicImages).toHaveLength(2)
  })

  it('mosaic images are capped at 5', () => {
    const images = Array.from({ length: 8 }, (_, i) =>
      makeImage({ id: i + 1, group_id: 100, name: `Img ${i + 1}` }),
    )

    const { result } = renderHook(() => useImageGrouping({ images }))

    const group = result.current.find((g) => g.groupId === 100)!
    expect(group.mosaicImages).toHaveLength(5)
  })

  it('uses group_image_count for totalScenes when available', () => {
    const images = [
      makeImage({ id: 1, group_id: 100, group_image_count: 25 }),
      makeImage({ id: 2, group_id: 100, group_image_count: 25 }),
    ]

    const { result } = renderHook(() => useImageGrouping({ images }))

    const group = result.current.find((g) => g.groupId === 100)!
    expect(group.totalScenes).toBe(25)
    expect(group.matchingCount).toBe(2) // only 2 in search results
  })

  it('falls back to matchingCount when group_image_count is null', () => {
    const images = [
      makeImage({ id: 1, group_id: 100 }),
      makeImage({ id: 2, group_id: 100 }),
      makeImage({ id: 3, group_id: 100 }),
    ]

    const { result } = renderHook(() => useImageGrouping({ images }))

    const group = result.current.find((g) => g.groupId === 100)!
    expect(group.totalScenes).toBe(3)
  })
})

// ── Tag aggregation ───────────────────────────────────────────────────────────

describe('useImageGrouping — Tag aggregation', () => {
  it('deduplicates tags across group images by category:value', () => {
    const images = [
      makeImage({
        id: 1,
        group_id: 100,
        tags: [makeTag('env', 'forest'), makeTag('time', 'night')],
      }),
      makeImage({
        id: 2,
        group_id: 100,
        tags: [makeTag('env', 'forest'), makeTag('env', 'cave')],
      }),
    ]

    const { result } = renderHook(() => useImageGrouping({ images }))

    const group = result.current.find((g) => g.groupId === 100)!
    const tagKeys = group.aggregatedTags.map((t) => `${t.category}:${t.value}`)
    expect(tagKeys).toEqual(['env:forest', 'time:night', 'env:cave'])
  })
})

// ── Sorting ───────────────────────────────────────────────────────────────────

describe('useImageGrouping — Sorting', () => {
  it('sorts by relevance when scores provided', () => {
    const images = [makeImage({ id: 1, name: 'Low' }), makeImage({ id: 2, name: 'High' })]
    const scores = { 1: 0.3, 2: 0.9 }

    const { result } = renderHook(() => useImageGrouping({ images, scores, sortBy: 'relevance' }))

    expect(result.current[0].baseName).toBe('High')
    expect(result.current[1].baseName).toBe('Low')
  })

  it('sorts by created_at descending by default', () => {
    const images = [
      makeImage({ id: 1, name: 'Older', created_at: '2025-01-01T00:00:00Z' }),
      makeImage({ id: 2, name: 'Newer', created_at: '2025-06-01T00:00:00Z' }),
    ]

    const { result } = renderHook(() => useImageGrouping({ images }))

    expect(result.current[0].baseName).toBe('Newer')
    expect(result.current[1].baseName).toBe('Older')
  })

  it('sorts by created_at ascending when sortDir is asc', () => {
    const images = [
      makeImage({ id: 1, name: 'Older', created_at: '2025-01-01T00:00:00Z' }),
      makeImage({ id: 2, name: 'Newer', created_at: '2025-06-01T00:00:00Z' }),
    ]

    const { result } = renderHook(() =>
      useImageGrouping({ images, sortBy: 'created_at', sortDir: 'asc' }),
    )

    expect(result.current[0].baseName).toBe('Older')
    expect(result.current[1].baseName).toBe('Newer')
  })

  it('sorts by name alphabetically', () => {
    const images = [
      makeImage({ id: 1, name: 'Cave' }),
      makeImage({ id: 2, name: 'Dungeon' }),
      makeImage({ id: 3, name: 'Beach' }),
    ]

    const { result } = renderHook(() =>
      useImageGrouping({ images, sortBy: 'name', sortDir: 'asc' }),
    )

    expect(result.current.map((g) => g.baseName)).toEqual(['Beach', 'Cave', 'Dungeon'])
  })

  it('hero image uses highest score when scores provided', () => {
    const images = [
      makeImage({ id: 1, group_id: 100, name: 'Low Score' }),
      makeImage({ id: 2, group_id: 100, name: 'High Score' }),
    ]
    const scores = { 1: 0.2, 2: 0.8 }

    const { result } = renderHook(() => useImageGrouping({ images, scores, sortBy: 'relevance' }))

    const group = result.current.find((g) => g.groupId === 100)!
    expect(group.heroImage.id).toBe(2)
    expect(group.bestScore).toBe(0.8)
  })
})
