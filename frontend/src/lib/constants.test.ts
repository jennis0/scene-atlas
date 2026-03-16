import { describe, it, expect } from 'vitest'
import { relevanceToPercent, RELEVANCE_MIN, RELEVANCE_MAX } from './constants'

describe('relevanceToPercent', () => {
  it('maps RELEVANCE_MIN to 0%', () => {
    expect(relevanceToPercent(RELEVANCE_MIN)).toBe(0)
  })

  it('maps RELEVANCE_MAX to 100%', () => {
    expect(relevanceToPercent(RELEVANCE_MAX)).toBe(100)
  })

  it('maps midpoint to 50%', () => {
    const mid = (RELEVANCE_MIN + RELEVANCE_MAX) / 2
    expect(relevanceToPercent(mid)).toBe(50)
  })

  it('maps quarter point to 25%', () => {
    const quarter = RELEVANCE_MIN + (RELEVANCE_MAX - RELEVANCE_MIN) * 0.25
    expect(relevanceToPercent(quarter)).toBe(25)
  })

  it('does not clamp values below min', () => {
    // Below min should produce negative percentages
    expect(relevanceToPercent(RELEVANCE_MIN - RELEVANCE_MAX)).toBeLessThan(0)
  })

  it('does not clamp values above max', () => {
    // Above max should produce >100%
    expect(relevanceToPercent(RELEVANCE_MAX * 2)).toBeGreaterThan(100)
  })
})
