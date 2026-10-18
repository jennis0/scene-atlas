import { afterEach, describe, expect, it, vi } from 'vitest'
import { cssColorToHex, reportWindowColors } from './windowColors'

describe('cssColorToHex', () => {
  it('converts computed rgb colours', () => {
    expect(cssColorToHex('rgb(14, 17, 24)')).toBe('#0e1118')
    expect(cssColorToHex('rgb(237,232,220)')).toBe('#ede8dc')
    expect(cssColorToHex('rgba(14, 17, 24, 1)')).toBe('#0e1118')
  })

  it('rejects transparent and unparseable colours', () => {
    expect(cssColorToHex('rgba(0, 0, 0, 0)')).toBeNull()
    expect(cssColorToHex('transparent')).toBeNull()
    expect(cssColorToHex('')).toBeNull()
  })
})

describe('reportWindowColors', () => {
  afterEach(() => {
    delete (window as { electronAPI?: unknown }).electronAPI
    document.body.removeAttribute('style')
  })

  it("sends the page's background and text colours to the desktop window", () => {
    const setWindowColors = vi.fn().mockResolvedValue(undefined)
    ;(window as { electronAPI?: unknown }).electronAPI = { setWindowColors }
    document.body.style.backgroundColor = 'rgb(14, 17, 24)'
    document.body.style.color = 'rgb(237, 232, 220)'
    reportWindowColors()
    expect(setWindowColors).toHaveBeenCalledWith({ background: '#0e1118', foreground: '#ede8dc' })
  })

  it('sends nothing without colours to report', () => {
    const setWindowColors = vi.fn().mockResolvedValue(undefined)
    ;(window as { electronAPI?: unknown }).electronAPI = { setWindowColors }
    reportWindowColors()
    expect(setWindowColors).not.toHaveBeenCalled()
  })

  it('is a no-op in the browser', () => {
    expect(() => reportWindowColors()).not.toThrow()
  })
})
