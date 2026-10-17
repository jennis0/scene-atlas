import { useSyncExternalStore } from 'react'
import { displayChoice } from './displayChoice'

/**
 * Contrast, independent of palette and light/dark: High lifts text to >= 7:1 (WCAG AAA)
 * and control outlines to >= 3:1 in every palette (see index.css), and strengthens the
 * shading behind names on images. Auto follows the system's "increase contrast" setting.
 * The effective result is data-contrast="high" on <html>.
 */
export type Contrast = 'auto' | 'standard' | 'high'
export const CONTRAST_OPTIONS: readonly { value: Contrast; label: string; title: string }[] = [
  { value: 'auto', label: 'Auto', title: "Follow the system's contrast setting" },
  { value: 'standard', label: 'Standard', title: 'Standard contrast' },
  { value: 'high', label: 'High', title: 'Stronger text, outlines and image captions' },
]

/** Saved per device; the preference itself is data-contrast-pref on <html>. */
export const contrastChoice = displayChoice<Contrast>(
  'scene-atlas-contrast',
  'contrastPref',
  CONTRAST_OPTIONS.map((o) => o.value),
  'auto',
)

const html = () => document.documentElement
const systemMore = () => window.matchMedia?.('(prefers-contrast: more)').matches ?? false

function update() {
  const pref = html().dataset.contrastPref
  const high = pref === 'high' || (pref !== 'standard' && systemMore())
  if (high) html().dataset.contrast = 'high'
  else delete html().dataset.contrast
}

/** Call once at startup, before first paint. */
export function watchContrast() {
  contrastChoice.apply(contrastChoice.read())
  update()
  window.matchMedia?.('(prefers-contrast: more)').addEventListener?.('change', update)
  new MutationObserver(update).observe(html(), {
    attributes: true,
    attributeFilter: ['data-contrast-pref'],
  })
}

function subscribe(onChange: () => void) {
  const observer = new MutationObserver(onChange)
  observer.observe(html(), { attributes: true, attributeFilter: ['data-contrast'] })
  return () => observer.disconnect()
}

/** Whether high contrast is in effect (the setting, or Auto with the system asking). */
export function useHighContrast(): boolean {
  return useSyncExternalStore(subscribe, () => html().dataset.contrast === 'high')
}
