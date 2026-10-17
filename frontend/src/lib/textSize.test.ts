import { describe, it, expect, beforeEach } from 'vitest'
import {
  applyTextSize,
  getStoredTextSize,
  saveTextSize,
  TEXT_SIZE_STORAGE_KEY,
  TEXT_SIZES,
} from './textSize'

describe('textSize', () => {
  beforeEach(() => {
    localStorage.clear()
    delete document.documentElement.dataset.textSize
  })

  it('defaults to default, including for unknown stored values', () => {
    expect(getStoredTextSize()).toBe('default')
    localStorage.setItem(TEXT_SIZE_STORAGE_KEY, 'huge')
    expect(getStoredTextSize()).toBe('default')
  })

  it('reads every saved size', () => {
    for (const { value } of TEXT_SIZES) {
      localStorage.setItem(TEXT_SIZE_STORAGE_KEY, value)
      expect(getStoredTextSize()).toBe(value)
    }
  })

  it('sets data-text-size for non-default sizes and clears it for default', () => {
    applyTextSize('large')
    expect(document.documentElement.dataset.textSize).toBe('large')
    applyTextSize('default')
    expect(document.documentElement.dataset.textSize).toBeUndefined()
  })

  it('save stores and applies', () => {
    saveTextSize('larger')
    expect(localStorage.getItem(TEXT_SIZE_STORAGE_KEY)).toBe('larger')
    expect(document.documentElement.dataset.textSize).toBe('larger')
  })
})
