import { describe, expect, it } from 'vitest'
import { planReviewBatches } from './useEditGroupLoad'

const ids = (n: number) => Array.from({ length: n }, (_, i) => i + 1)

describe('planReviewBatches', () => {
  it('starts with a small batch, then bigger ones, in order', () => {
    const { batches, startFirst } = planReviewBatches(ids(100), undefined)
    expect(startFirst).toBe(false)
    expect(batches.map((b) => b.length)).toEqual([8, 40, 40, 12])
    expect(batches.flat()).toEqual(ids(100))
  })

  it('gives the start group a batch of its own, first, and keeps the rest in order', () => {
    const { batches, startFirst } = planReviewBatches(ids(10), 7)
    expect(startFirst).toBe(true)
    expect(batches).toEqual([[7], [1, 2, 3, 4, 5, 6, 8, 9, 10]])
  })

  it('ignores a start group that is not among the ids', () => {
    const { batches, startFirst } = planReviewBatches(ids(3), 42)
    expect(startFirst).toBe(false)
    expect(batches).toEqual([[1, 2, 3]])
  })
})
