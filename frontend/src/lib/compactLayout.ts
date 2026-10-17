import { useSyncExternalStore } from 'react'
import { displayChoice } from './displayChoice'

/**
 * Layout for short windows. Browser zoom and the text size setting both shrink how many
 * lines of text fit vertically, so this measures the window height in rem (a media
 * query would only see px) and sets data-short on <html>:
 * - the image viewer's details panel scrolls with the scenes (the `short:` variant);
 * - the gallery header goes compact, unless the compact header setting says otherwise.
 */
const SHORT_BELOW_REM = 44 // ~750px tall at the default 17px text

export type CompactHeader = 'auto' | 'on' | 'off'
export const COMPACT_HEADER_OPTIONS: readonly {
  value: CompactHeader
  label: string
  title: string
}[] = [
  {
    value: 'auto',
    label: 'Auto',
    title: 'Compact when the window is short (zoomed in or large text)',
  },
  { value: 'on', label: 'On', title: 'Always use the compact header' },
  { value: 'off', label: 'Off', title: 'Always use the full header' },
]

/** Saved per device; set as data-compact-header on <html> (auto sets nothing). */
export const compactHeaderChoice = displayChoice<CompactHeader>(
  'scene-atlas-compact-header',
  'compactHeader',
  COMPACT_HEADER_OPTIONS.map((o) => o.value),
  'auto',
)

const root = () => document.documentElement

function updateShort() {
  const rootPx = parseFloat(getComputedStyle(root()).fontSize) || 16
  if (window.innerHeight / rootPx < SHORT_BELOW_REM) root().dataset.short = ''
  else delete root().dataset.short
}

/** Call once at startup, before first paint. */
export function watchShortWindow() {
  compactHeaderChoice.apply(compactHeaderChoice.read())
  updateShort()
  window.addEventListener('resize', updateShort)
  new MutationObserver(updateShort).observe(root(), {
    attributes: true,
    attributeFilter: ['data-text-size'],
  })
}

/** Whether the gallery header should be compact: the setting, or (auto) a short window. */
export function isCompactHeader(): boolean {
  const pref = root().dataset.compactHeader
  return pref === 'on' || (pref !== 'off' && 'short' in root().dataset)
}

function subscribe(onChange: () => void) {
  const observer = new MutationObserver(onChange)
  observer.observe(root(), {
    attributes: true,
    attributeFilter: ['data-short', 'data-compact-header'],
  })
  return () => observer.disconnect()
}

export function useCompactHeader(): boolean {
  return useSyncExternalStore(subscribe, isCompactHeader)
}
