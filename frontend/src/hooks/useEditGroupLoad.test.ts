import { describe, expect, it } from 'vitest'
import { ALL_TAB } from '@/hooks/useFileEditing'
import type { GroupSummary } from '@/types'
import { ALL_VIEW_IMAGE_LIMIT, initialReviewTab, nextReviewBatch } from './useEditGroupLoad'

const ids = (n: number) => Array.from({ length: n }, (_, i) => i + 1)

describe('nextReviewBatch', () => {
  it('takes a small batch until something is shown, then bigger ones, in order', () => {
    expect(nextReviewBatch(ids(100), null, false)).toEqual(ids(8))
    expect(nextReviewBatch(ids(100), null, true)).toEqual(ids(40))
  })

  it('sends a group the user is waiting on alone and first', () => {
    expect(nextReviewBatch(ids(10), 7, false)).toEqual([7])
    expect(nextReviewBatch(ids(10), 7, true)).toEqual([7])
  })

  it('ignores a priority group that is not queued', () => {
    expect(nextReviewBatch([1, 2, 3], 42, true)).toEqual([1, 2, 3])
  })
})

const summary = (id: number, image_count: number): GroupSummary => ({
  id,
  base_name: `Group ${id}`,
  author: null,
  primary_image_id: null,
  image_count,
  image_ids: [],
})

describe('initialReviewTab', () => {
  it('opens on All for several groups', () => {
    expect(initialReviewTab([summary(1, 10), summary(2, 10)], false)).toBe(ALL_TAB)
  })

  it('opens on the first group for one group, or when a start group was asked for', () => {
    expect(initialReviewTab([summary(1, 10)], false)).toBe(0)
    expect(initialReviewTab([summary(1, 10), summary(2, 10)], true)).toBe(0)
  })

  it('opens on the first group when All would hold too many images', () => {
    const big = [summary(1, ALL_VIEW_IMAGE_LIMIT), summary(2, 1)]
    expect(initialReviewTab(big, false)).toBe(0)
  })
})
