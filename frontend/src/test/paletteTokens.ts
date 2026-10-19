/**
 * Reads the palette token blocks out of index.css and resolves them the way the cascade
 * does on <html>, for contrast tests. Read from disk: the test config stubs CSS imports
 * (css: false), even with ?raw.
 */
import { readFileSync } from 'node:fs'
import path from 'node:path'
import type { Palette } from '@/lib/palette'

export type Mode = 'light' | 'dark'
export type ContrastLevel = 'standard' | 'high'
export type Hsl = [number, number, number]
type Tokens = Record<string, Hsl>
/** A token's value in a block: an HSL triplet, or a reference to another token
 * (`--x: var(--y)`), which the browser resolves against the final cascade. */
type Value = Hsl | { ref: string }

const css = readFileSync(path.resolve(__dirname, '../index.css'), 'utf8').replace(
  /\/\*[\s\S]*?\*\//g,
  '',
)

const mode = (dark: string | undefined) => (dark ? 'dark' : 'light')

/** Token block selectors, each with the block key (palette/mode, plus /hc for high
 * contrast) it sets tokens for. */
const TARGETS: [RegExp, (m: RegExpMatchArray) => string][] = [
  [/^:root$/, () => 'navy/light'],
  [/^\.dark$/, () => 'navy/dark'],
  [/^(\.dark)?\s*\[data-palette='([a-z]+)'\]$/, (m) => `${m[2]}/${mode(m[1])}`],
  // High contrast: on <html> ([data-contrast='high'][data-palette='x'], or :not([data-palette])
  // for navy, the default), or nested ([data-contrast='high'] [data-palette='x'])
  [
    /^(\.dark)?\[data-contrast='high'\](?::not\(\[data-palette\]\)|\s*\[data-palette='([a-z]+)'\])$/,
    (m) => `${m[2] ?? 'navy'}/${mode(m[1])}/hc`,
  ],
  // High contrast for tokens every palette shares (status colours)
  [/^(\.dark)?\[data-contrast='high'\]$/, (m) => `all/${mode(m[1])}/hc`],
]

/** The block key a selector sets tokens for, or null if it is not a token block. */
function target(selector: string): string | null {
  for (const [pattern, key] of TARGETS) {
    const m = selector.match(pattern)
    if (m) return key(m)
  }
  return null
}

export const blocks = new Map<string, Record<string, Value>>()
for (const [, selectorList, body] of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
  const tokens: Record<string, Value> = {}
  for (const [, name, h, s, l] of body.matchAll(
    /--([a-z-]+):\s*([\d.]+)\s+([\d.]+)%\s+([\d.]+)%/g,
  )) {
    tokens[name] = [Number(h), Number(s), Number(l)]
  }
  for (const [, name, ref] of body.matchAll(/--([a-z-]+):\s*var\(--([a-z-]+)\)/g)) {
    tokens[name] = { ref }
  }
  if (Object.keys(tokens).length === 0) continue
  for (const selector of selectorList.split(',')) {
    const key = target(selector.trim())
    if (key) blocks.set(key, { ...blocks.get(key), ...tokens })
  }
}

/** Cascade on <html>: base light, base dark, palette light, palette dark, then for high
 * contrast the shared blocks and the palette's own (later wins). */
export function resolve(palette: Palette, mode: Mode, level: ContrastLevel): Tokens {
  const layers = ['navy/light', mode === 'dark' && 'navy/dark', `${palette}/light`]
  if (mode === 'dark') layers.push(`${palette}/dark`)
  if (level === 'high') {
    layers.push('all/light/hc')
    if (mode === 'dark') layers.push('all/dark/hc')
    layers.push(`${palette}/light/hc`)
    if (mode === 'dark') layers.push(`${palette}/dark/hc`)
  }
  const merged: Record<string, Value> = Object.assign(
    {},
    ...layers.filter(Boolean).map((k) => blocks.get(k as string)),
  )
  // References resolve against the final values, as var() does on the element
  const tokens: Tokens = {}
  for (const [name, value] of Object.entries(merged)) {
    tokens[name] = 'ref' in value ? (merged[value.ref] as Hsl) : value
  }
  return tokens
}

/** sRGB channels in 0..1, rounded to 8 bits as the browser renders them (axe measures
 * the rendered colour, so an unrounded 7.0 can come out as 6.99). */
export function rgb([h, s, l]: Hsl): number[] {
  const a = (s / 100) * Math.min(l / 100, 1 - l / 100)
  const f = (n: number) => {
    const k = (n + h / 30) % 12
    return Math.round((l / 100 - a * Math.max(-1, Math.min(k - 3, 9 - k, 1))) * 255) / 255
  }
  return [f(0), f(8), f(4)]
}

export function hex(value: string): number[] {
  const n = parseInt(value.slice(1), 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) => v / 255)
}

function luminance(c: number[]): number {
  const [r, g, b] = c.map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4))
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

export function contrast(a: number[], b: number[]): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

/** `top` at `alpha` over `bottom`, as a translucent fill renders (rounded to 8 bits). */
export function over(top: number[], alpha: number, bottom: number[]): number[] {
  return top.map((v, i) => Math.round((v * alpha + bottom[i] * (1 - alpha)) * 255) / 255)
}

export const SURFACES = ['background', 'card', 'popover', 'secondary', 'muted']
