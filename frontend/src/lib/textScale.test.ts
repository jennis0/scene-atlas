/**
 * The smallest text must stay readable at every text size, and grow faster than the rest
 * at the large steps. Reads index.css (the test config stubs CSS imports) and resolves
 * the root size and the text-3xs / text-2xs variables for each step.
 */
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { describe, it, expect } from 'vitest'
import { TEXT_SIZES, type TextSize } from './textSize'

const css = readFileSync(path.resolve(__dirname, '../index.css'), 'utf8').replace(
  /\/\*[\s\S]*?\*\//g,
  '',
)

function block(selector: string): string {
  const m = css.match(
    new RegExp(`(?:^|\\})\\s*${selector.replace(/[[\]']/g, '\\$&')}\\s*\\{([^}]*)\\}`),
  )
  if (!m) throw new Error(`no block for ${selector}`)
  return m[1]
}

function sizes(step: TextSize) {
  const base = block('html')
  const own = step === 'default' ? '' : block(`html[data-text-size='${step}']`)
  const get = (body: string, prop: string) => body.match(new RegExp(`${prop}:\\s*([\\d.]+)`))?.[1]
  const pick = (prop: string) => Number(get(own, prop) ?? get(base, prop))
  const rootPx = (pick('font-size') / 100) * 16
  return { rootPx, xs3: pick('--text-3xs') * rootPx, xs2: pick('--text-2xs') * rootPx }
}

const FLOOR: Record<TextSize, number> = { small: 10.5, default: 11, large: 12.5, larger: 14 }

describe.each(TEXT_SIZES.map((t) => t.value))('%s text size', (step) => {
  const { xs3, xs2 } = sizes(step)

  it(`smallest text is at least ${FLOOR[step]}px`, () => {
    expect(xs3).toBeGreaterThanOrEqual(FLOOR[step] - 0.05)
    expect(xs2).toBeGreaterThan(xs3)
  })
})

it('the large steps raise small text faster than the root', () => {
  const base = sizes('default')
  for (const step of ['large', 'larger'] as const) {
    const s = sizes(step)
    expect(s.xs3 / base.xs3).toBeGreaterThan(s.rootPx / base.rootPx)
  }
})
