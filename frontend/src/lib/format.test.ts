import { describe, it, expect } from 'vitest'
import { fullImageName } from './format'

describe('fullImageName', () => {
  it.each([
    ['Snowy', 'Frozen Lake', 'Frozen Lake Snowy'],
    ['Frozen Lake Snowy', 'Frozen Lake', 'Frozen Lake Snowy'],
    ['frozen lake night', 'Frozen Lake', 'frozen lake night'],
    ['Snowy', null, 'Snowy'],
  ])('%s in %s is %s', (name, group_name, expected) => {
    expect(fullImageName({ name, group_name })).toBe(expected)
  })
})
