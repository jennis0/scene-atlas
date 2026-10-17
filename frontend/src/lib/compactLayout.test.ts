import { describe, it, expect, beforeAll, beforeEach } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import {
  compactHeaderChoice,
  isCompactHeader,
  useCompactHeader,
  watchShortWindow,
} from './compactLayout'

const html = document.documentElement

function setWindowHeight(px: number) {
  Object.defineProperty(window, 'innerHeight', { configurable: true, value: px })
  window.dispatchEvent(new Event('resize'))
}

describe('compact layout', () => {
  beforeAll(() => {
    html.style.fontSize = '17px'
    watchShortWindow()
  })

  beforeEach(() => {
    localStorage.clear()
    compactHeaderChoice.apply('auto')
    setWindowHeight(1000)
  })

  it('marks the window short when fewer than ~44 lines of text fit', () => {
    expect('short' in html.dataset).toBe(false) // 1000 / 17 ≈ 59 lines
    setWindowHeight(640) // ≈ 38 lines
    expect('short' in html.dataset).toBe(true)
  })

  it('re-measures when the text size changes', async () => {
    setWindowHeight(800) // 47 lines at 17px: not short
    expect('short' in html.dataset).toBe(false)
    html.style.fontSize = '21px' // what data-text-size="larger" does via CSS
    html.dataset.textSize = 'larger'
    await Promise.resolve() // MutationObserver callbacks run as microtasks
    expect('short' in html.dataset).toBe(true) // 800 / 21 ≈ 38 lines
    html.style.fontSize = '17px'
    delete html.dataset.textSize
  })

  it('compact header: auto follows the window, on and off override it', () => {
    expect(isCompactHeader()).toBe(false)
    setWindowHeight(640)
    expect(isCompactHeader()).toBe(true)

    compactHeaderChoice.save('off')
    expect(isCompactHeader()).toBe(false)
    expect(localStorage.getItem('scene-atlas-compact-header')).toBe('off')

    setWindowHeight(1000)
    compactHeaderChoice.save('on')
    expect(isCompactHeader()).toBe(true)
  })

  it('useCompactHeader re-renders when the window or setting changes', async () => {
    const { result } = renderHook(() => useCompactHeader())
    expect(result.current).toBe(false)
    await act(async () => setWindowHeight(640))
    expect(result.current).toBe(true)
    await act(async () => compactHeaderChoice.save('off'))
    expect(result.current).toBe(false)
  })
})
