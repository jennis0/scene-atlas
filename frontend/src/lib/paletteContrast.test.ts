/**
 * Every palette must keep its text legible in both modes, at standard and high contrast.
 * This reads the token blocks straight out of index.css, resolves them the way the
 * cascade does on <html>, and checks WCAG contrast — so a new or retuned palette fails
 * here before it reaches the axe scan. High contrast must reach AAA (7:1) for text.
 */
import { describe, it, expect } from 'vitest'
import { PALETTES } from './palette'
import { blocks, contrast, over, resolve, rgb, SURFACES } from '@/test/paletteTokens'

// Text colours: text-primary, text-destructive, text-success and text-warning use the
// ink variants (tailwind.config.js textColor)
const TEXT = [
  'foreground',
  'muted-foreground',
  'primary-ink',
  'destructive-ink',
  'success-ink',
  'warning-ink',
]

/** Standard is WCAG AA; high contrast is AAA for text, with outlines that show controls. */
const MIN = {
  standard: { text: 4.5, filled: 4.5 },
  high: { text: 7, filled: 7 },
}

const VARIANTS = PALETTES.flatMap((p) =>
  (['light', 'dark'] as const).flatMap((mode) =>
    (['standard', 'high'] as const).map((level) => [p.value, mode, level] as const),
  ),
)

describe.each(VARIANTS)('%s palette, %s mode, %s contrast', (palette, mode, level) => {
  const t = resolve(palette, mode, level)
  const c = (name: string) => rgb(t[name])
  const min = MIN[level]

  it('defines its tokens in index.css', () => {
    expect(blocks.has(`${palette}/${mode}${level === 'high' ? '/hc' : ''}`)).toBe(true)
  })

  it.each(TEXT.flatMap((text) => SURFACES.map((surface) => [text, surface])))(
    `%s text on %s is >= ${min.text}:1`,
    (text, surface) => {
      expect(contrast(c(text), c(surface))).toBeGreaterThanOrEqual(min.text)
    },
  )

  it('primary-ink stays legible on a primary tint, up to /20 (counts, chips)', () => {
    for (const surface of SURFACES) {
      const tint = over(c('primary'), 0.2, c(surface))
      expect(contrast(c('primary-ink'), tint)).toBeGreaterThanOrEqual(min.text)
    }
  })

  it('status text stays legible on its own tint, up to /20 (status chips)', () => {
    for (const status of ['success', 'warning', 'destructive']) {
      for (const surface of SURFACES) {
        const tint = over(c(status), 0.2, c(surface))
        expect(
          contrast(c(`${status}-ink`), tint),
          `${status} on ${surface}`,
        ).toBeGreaterThanOrEqual(min.text)
      }
    }
  })

  it('filled controls keep their labels legible', () => {
    expect(contrast(c('primary-foreground'), c('primary'))).toBeGreaterThanOrEqual(min.filled)
    // Destructive fills are rare (confirm buttons); AA is enough for their labels
    expect(contrast(c('destructive-foreground'), c('destructive'))).toBeGreaterThanOrEqual(4.5)
  })

  if (level === 'high') {
    it('control outlines are >= 3:1 and dividers >= 2:1', () => {
      for (const surface of ['background', 'card', 'popover']) {
        expect(contrast(c('input'), c(surface))).toBeGreaterThanOrEqual(3)
      }
      for (const surface of ['background', 'card']) {
        expect(contrast(c('border'), c(surface))).toBeGreaterThanOrEqual(2)
      }
    })
  }

  it("the logo's pages stand out from the page background (>= 3:1, non-text)", () => {
    expect(contrast(c('mark-page'), c('background'))).toBeGreaterThanOrEqual(3)
  })

  it('focus ring is >= 3:1 on every surface', () => {
    for (const surface of SURFACES) {
      expect(contrast(c('ring'), c(surface))).toBeGreaterThanOrEqual(3)
    }
  })
})

it('dark palette blocks override every token their light block sets', () => {
  // The light block also matches <html> in dark mode, so anything it sets that the dark
  // block does not would leak a light-mode value into dark mode.
  // High contrast blocks follow the same rule, navy included.
  for (const { value } of PALETTES) {
    for (const suffix of value === 'navy' ? ['/hc'] : ['', '/hc']) {
      const light = Object.keys(blocks.get(`${value}/light${suffix}`) ?? {})
      const dark = Object.keys(blocks.get(`${value}/dark${suffix}`) ?? {})
      expect(light.filter((k) => !dark.includes(k))).toEqual([])
    }
  }
})
