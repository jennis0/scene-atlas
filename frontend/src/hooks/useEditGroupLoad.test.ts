import { describe, expect, it } from 'vitest'
import { planReviewBatches } from './useEditGroupLoad'

const ids = (n: number) => Array.from({ length: n }, (_, i) => i + 1)

describe('planReviewBatches', () => {
  it('splits ids into batches of 8, in order', () => {
    const { batches, startFirst } = planReviewBatches(ids(19), undefined)
    expect(startFirst).toBe(false)
    expect(batches.map((b) => b.length)).toEqual([8, 8, 3])
    expect(batches.flat()).toEqual(ids(19))
  })

  it('gives the start group a batch of its own, first, and keeps the rest in order', () => {
    const { batches, startFirst } = planReviewBatches(ids(10), 7)
    expect(startFirst).toBe(true)
    expect(batches[0]).toEqual([7])
    expect(batches.slice(1).flat()).toEqual([1, 2, 3, 4, 5, 6, 8, 9, 10])
  })

  it('ignores a start group that is not among the ids', () => {
    const { batches, startFirst } = planReviewBatches(ids(3), 42)
    expect(startFirst).toBe(false)
    expect(batches).toEqual([[1, 2, 3]])
  })
})
