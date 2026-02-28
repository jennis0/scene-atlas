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
    expect(relevanceToPercent(0.3)).toBe(50)
  })

  it('maps quarter point to 25%', () => {
    expect(relevanceToPercent(0.2)).toBe(25)
  })

  it('does not clamp values below min', () => {
    expect(relevanceToPercent(0.0)).toBe(-25)
  })

  it('does not clamp values above max', () => {
    expect(relevanceToPercent(0.9)).toBe(200)
  })
})
