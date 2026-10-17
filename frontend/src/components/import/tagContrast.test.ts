/**
 * Tag chips use their own colours (Tailwind classes per category) rather than the palette
 * tokens, so check them against every palette's surfaces: AA (4.5:1) at standard
 * contrast, AAA (7:1) at high contrast.
 */
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { describe, it, expect } from 'vitest'
import colors from 'tailwindcss/colors'
import { getTagColor, PALETTE_KEYS, TAG_HUES } from './tagColors'
import { PALETTES } from '@/lib/palette'
import { contrast, hex, over, resolve, rgb, SURFACES, type Mode } from '@/test/paletteTokens'

const shades = colors as unknown as Record<string, Record<string, string>>

/** RGB and alpha of a Tailwind colour class such as text-red-300 or bg-red-400/10. */
function classColor(cls: string): { rgb: number[]; alpha: number } {
  const m = cls.match(/^[a-z]+-([a-z]+)-(\d+)(?:\/(\d+))?$/)
  if (!m) throw new Error(`unexpected class ${cls}`)
  return { rgb: hex(shades[m[1]][m[2]]), alpha: m[3] ? Number(m[3]) / 100 : 1 }
}

const LEVELS = [
  ['standard', false, 4.5],
  ['high', true, 7],
] as const

describe.each(LEVELS)('%s contrast', (_level, high, min) => {
  for (const mode of ['dark', 'light'] as Mode[]) {
    it(`${mode}: every tag colour's text is >= ${min}:1 on its chip and bare, on every palette`, () => {
      const failures: string[] = []
      for (const key of [...PALETTE_KEYS, null]) {
        const chip = getTagColor(key, mode, high)
        const text = classColor(chip.text).rgb
        const tint = classColor(chip.bg)
        for (const { value: palette } of PALETTES) {
          const tokens = resolve(palette, mode, high ? 'high' : 'standard')
          for (const surface of SURFACES) {
            // On its chip, and bare on the surface (category names in lists)
            const backgrounds = {
              chip: over(tint.rgb, tint.alpha, rgb(tokens[surface])),
              bare: rgb(tokens[surface]),
            }
            for (const [where, background] of Object.entries(backgrounds)) {
              const ratio = contrast(text, background)
              if (ratio < min)
                failures.push(
                  `${key ?? 'default'} ${where} on ${palette} ${surface}: ${ratio.toFixed(2)}`,
                )
            }
          }
        }
      }
      expect(failures).toEqual([])
    })
  }
})

it('tailwind.config.js safelists the high-contrast classes for every tag hue', () => {
  const config = readFileSync(path.resolve(__dirname, '../../../tailwind.config.js'), 'utf8')
  const lists = [...config.matchAll(/(?:text|border)-\(([a-z|]+)\)/g)].map((m) => m[1].split('|'))
  expect(lists).toHaveLength(2)
  for (const list of lists) expect([...list].sort()).toEqual([...TAG_HUES].sort())
})
