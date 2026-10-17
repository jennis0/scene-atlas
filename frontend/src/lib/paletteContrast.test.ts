/**
 * Every palette must keep its text legible in both modes. This reads the token blocks
 * straight out of index.css, resolves them the way the cascade does on <html>, and checks
 * WCAG contrast — so a new or retuned palette fails here before it reaches the axe scan.
 */
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { describe, it, expect } from 'vitest'
import { PALETTES, type Palette } from './palette'

type Mode = 'light' | 'dark'
type Tokens = Record<string, [number, number, number]>

// Read from disk: the test config stubs CSS imports (css: false), even with ?raw
const css = readFileSync(path.resolve(__dirname, '../index.css'), 'utf8').replace(
  /\/\*[\s\S]*?\*\//g,
  '',
)

/** Which (palette, mode) a selector sets tokens for, or null if it is not a token block. */
function target(selector: string): { palette: Palette; mode: Mode } | null {
  if (selector === ':root') return { palette: 'navy', mode: 'light' }
  if (selector === '.dark') return { palette: 'navy', mode: 'dark' }
  const m = selector.match(/^(\.dark)?\s*\[data-palette='([a-z]+)'\]$/)
  return m ? { palette: m[2] as Palette, mode: m[1] ? 'dark' : 'light' } : null
}

const blocks = new Map<string, Tokens>()
for (const [, selectorList, body] of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
  const tokens: Tokens = {}
  for (const [, name, h, s, l] of body.matchAll(
    /--([a-z-]+):\s*([\d.]+)\s+([\d.]+)%\s+([\d.]+)%/g,
  )) {
    tokens[name] = [Number(h), Number(s), Number(l)]
  }
  if (Object.keys(tokens).length === 0) continue
  for (const selector of selectorList.split(',')) {
    const t = target(selector.trim())
    if (t)
      blocks.set(`${t.palette}/${t.mode}`, { ...blocks.get(`${t.palette}/${t.mode}`), ...tokens })
  }
}

/** Cascade on <html>: base light, base dark, palette light, palette dark (later wins). */
function resolve(palette: Palette, mode: Mode): Tokens {
  const layers = ['navy/light', mode === 'dark' && 'navy/dark', `${palette}/light`]
  if (mode === 'dark') layers.push(`${palette}/dark`)
  return Object.assign({}, ...layers.filter(Boolean).map((k) => blocks.get(k as string)))
}

function rgb([h, s, l]: [number, number, number]): number[] {
  const a = (s / 100) * Math.min(l / 100, 1 - l / 100)
  const f = (n: number) => {
    const k = (n + h / 30) % 12
    return l / 100 - a * Math.max(-1, Math.min(k - 3, 9 - k, 1))
  }
  return [f(0), f(8), f(4)]
}

function luminance(c: number[]): number {
  const [r, g, b] = c.map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4))
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

function contrast(a: number[], b: number[]): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

/** `top` at `alpha` over `bottom`, as a primary/10 tint renders. */
function over(top: number[], alpha: number, bottom: number[]): number[] {
  return top.map((v, i) => v * alpha + bottom[i] * (1 - alpha))
}

const SURFACES = ['background', 'card', 'popover', 'secondary', 'muted']
const TEXT = ['foreground', 'muted-foreground', 'primary-ink', 'destructive']

describe.each(PALETTES.flatMap((p) => (['light', 'dark'] as const).map((mode) => [p.value, mode])))(
  '%s palette, %s mode',
  (palette, mode) => {
    const t = resolve(palette as Palette, mode as Mode)
    const c = (name: string) => rgb(t[name])

    it('defines its tokens in index.css', () => {
      expect(blocks.has(`${palette}/${mode}`)).toBe(true)
    })

    it.each(TEXT.flatMap((text) => SURFACES.map((surface) => [text, surface])))(
      '%s text on %s is >= 4.5:1',
      (text, surface) => {
        expect(contrast(c(text), c(surface))).toBeGreaterThanOrEqual(4.5)
      },
    )

    it('primary-ink stays legible on a primary/10 tint', () => {
      for (const surface of ['background', 'card']) {
        const tint = over(c('primary'), 0.1, c(surface))
        expect(contrast(c('primary-ink'), tint)).toBeGreaterThanOrEqual(4.5)
      }
    })

    it('filled controls keep their labels legible', () => {
      expect(contrast(c('primary-foreground'), c('primary'))).toBeGreaterThanOrEqual(4.5)
      expect(contrast(c('destructive-foreground'), c('destructive'))).toBeGreaterThanOrEqual(4.5)
    })

    it('focus ring is >= 3:1 on every surface', () => {
      for (const surface of SURFACES) {
        expect(contrast(c('ring'), c(surface))).toBeGreaterThanOrEqual(3)
      }
    })
  },
)

it('dark palette blocks override every token their light block sets', () => {
  // The light block also matches <html> in dark mode, so anything it sets that the dark
  // block does not would leak a light-mode value into dark mode.
  for (const { value } of PALETTES) {
    if (value === 'navy') continue
    const light = Object.keys(blocks.get(`${value}/light`) ?? {})
    const dark = Object.keys(blocks.get(`${value}/dark`) ?? {})
    expect(light.filter((k) => !dark.includes(k))).toEqual([])
  }
})
