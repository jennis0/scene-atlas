/**
 * Names on map thumbnails must stay readable over any image, including a pure-white map.
 * Reads the shading values from index.css (the test config stubs CSS imports) and checks
 * text over white at the lightest point behind the text: AA (4.5:1) at standard contrast,
 * AAA (7:1) at high contrast, where the captions also switch to full white.
 */
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { it, expect } from 'vitest'

const css = readFileSync(path.resolve(__dirname, '../index.css'), 'utf8')

/** Numeric custom properties set by every block with exactly this selector, merged. */
function vars(selector: string): Record<string, number> {
  const escaped = selector.replace(/[[\]'=]/g, '\\$&')
  const out: Record<string, number> = {}
  for (const [, body] of css.matchAll(new RegExp(`(?:^|[}\\s])${escaped}\\s*\\{([^}]*)\\}`, 'g'))) {
    for (const [, k, v] of body.matchAll(/--([a-z-]+):\s*([\d.]+)(?:;|\s*\/)/g)) out[k] = Number(v)
  }
  return out
}

const standard = vars(':root')
const high = { ...standard, ...vars("[data-contrast='high']") }

const luminance = (v: number) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4)
const contrast = (a: number, b: number) => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

/** White text at `textAlpha` over black shading at `shade` over a white image (grey levels). */
function overWhite(shade: number, textAlpha: number) {
  const background = 1 - shade
  const text = textAlpha + (1 - textAlpha) * background
  return contrast(text, background)
}

it('standard: names (white) and details (white/85) are >= 4.5:1 over a white map', () => {
  expect(overWhite(standard['scrim-text'], 1)).toBeGreaterThanOrEqual(4.5)
  expect(overWhite(standard['scrim-text'], 0.85)).toBeGreaterThanOrEqual(4.5)
  expect(overWhite(standard.band, 0.9)).toBeGreaterThanOrEqual(4.5)
})

it('high contrast: captions (full white) are >= 7:1 over a white map', () => {
  expect(overWhite(high['scrim-text'], 1)).toBeGreaterThanOrEqual(7)
  expect(overWhite(high.band, 1)).toBeGreaterThanOrEqual(7)
})

it('shading only gets darker towards the bottom', () => {
  for (const v of [standard, high])
    expect(v['scrim-bottom']).toBeGreaterThanOrEqual(v['scrim-text'])
})
