import { describe, it, expect } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import { partitionBySubgroup, useSceneFilters } from './useSceneFilters'
import type { Image } from '@/types'

function scene(id: number, overrides: Partial<Image> = {}): Image {
  return {
    id,
    name: `Scene ${id}`,
    filename: `scene_${id}.png`,
    subgroup: null,
    image_type: 'battlemap',
    media_type: 'image',
    gridded: null,
    grid_type: null,
    tags: [],
    ...overrides,
  } as Image
}

const tag = (category: string, value: string) => ({
  id: 0,
  image_id: 0,
  category,
  value,
  confidence: 1,
  source: 'manual',
})

describe('partitionBySubgroup', () => {
  it('keeps first-seen order and puts unlabelled scenes under Other', () => {
    const sections = partitionBySubgroup([
      scene(1, { subgroup: 'winter' }),
      scene(2),
      scene(3, { subgroup: 'summer' }),
      scene(4, { subgroup: 'winter' }),
    ])
    expect(sections.map((s) => [s.label, s.images.map((i) => i.id)])).toEqual([
      ['winter', [1, 4]],
      ['Other', [2]],
      ['summer', [3]],
    ])
  })

  it('returns one section for a single subgroup or none at all', () => {
    expect(partitionBySubgroup([scene(1), scene(2)])).toEqual([
      { label: 'Other', images: [scene(1), scene(2)] },
    ])
    expect(partitionBySubgroup([])).toEqual([{ label: 'All scenes', images: [] }])
  })
})

describe('useSceneFilters', () => {
  const scenes = [
    scene(1, { subgroup: 'night', tags: [tag('light', 'dark')] }),
    scene(2, { subgroup: 'day', media_type: 'video', tags: [tag('light', 'bright')] }),
    scene(3, { tags: [tag('light', 'dark')], image_type: 'scene' }),
  ]

  it('builds subgroup, media and tag groups with counts', () => {
    const { result } = renderHook(() => useSceneFilters(scenes))
    const groups = result.current.filterGroups
    expect(groups.map((g) => g.id)).toEqual(['subgroup', 'media_type', 'light'])
    expect(groups[0].options.map((o) => [o.label, o.count])).toEqual([
      ['day', 1],
      ['night', 1],
    ])
    expect(groups[1].options.map((o) => o.filterLabel)).toEqual(['media: Images', 'media: Videos'])
    // Most common value first
    expect(groups[2].options.map((o) => [o.label, o.count])).toEqual([
      ['dark', 2],
      ['bright', 1],
    ])
    expect(result.current.hasMixedTypes).toBe(true)
  })

  it('offers nothing to filter for a single scene', () => {
    const { result } = renderHook(() => useSceneFilters([scenes[0]]))
    expect(result.current.filterGroups).toEqual([])
    expect(result.current.hasMixedTypes).toBe(false)
  })

  it('ignores whitespace-only search and resets', () => {
    const { result } = renderHook(() => useSceneFilters(scenes))
    act(() => result.current.setFilter((f) => ({ ...f, text: '   ' })))
    expect(result.current.filtered).toHaveLength(3)

    act(() => result.current.setFilter((f) => ({ ...f, text: 'NIGHT' })))
    expect(result.current.filtered.map((s) => s.id)).toEqual([1])

    act(() => result.current.reset())
    expect(result.current.filter.text).toBe('')
    expect(result.current.filtered).toHaveLength(3)
  })

  it('combines include and exclude filters', () => {
    const { result } = renderHook(() => useSceneFilters(scenes))
    act(() =>
      result.current.setFilter((f) => ({
        ...f,
        active: [
          { type: 'tag', value: 'light:dark', label: 'dark', exclude: false },
          { type: 'subgroup', value: 'night', label: 'night', exclude: true },
        ],
      })),
    )
    expect(result.current.filtered.map((s) => s.id)).toEqual([3])
  })
})
