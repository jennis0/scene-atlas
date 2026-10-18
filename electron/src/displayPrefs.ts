// The UI's per-device display choices (theme, palette, text size, ...) and the window
// colours they produce, kept in the desktop app's config. The UI's own localStorage is tied
// to the backend's port, so it loses them when that port changes (design/first-run.md).
// Node-only (no electron import) so it can be unit tested with `node --test`.

/** Keys are the UI's localStorage keys; values are short tokens like "dark" or "lapis". */
export type DisplayPrefs = Record<string, string>

export interface WindowColors {
  background: string
  foreground: string
}

export type ThemeSource = 'system' | 'light' | 'dark'

const KEY = /^scene-atlas-[a-z0-9-]{1,48}$/
const VALUE = /^[a-z0-9-]{1,32}$/
const MAX_PREFS = 32
const HEX_COLOR = /^#[0-9a-f]{6}$/i

export const THEME_PREF_KEY = 'scene-atlas-theme'

export function isDisplayPref(key: unknown, value: unknown): key is string {
  return typeof key === 'string' && typeof value === 'string' && KEY.test(key) && VALUE.test(value)
}

/** The valid entries of *raw* (from the config file or the renderer), at most MAX_PREFS. */
export function sanitizeDisplayPrefs(raw: unknown): DisplayPrefs {
  const prefs: DisplayPrefs = {}
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return prefs
  for (const [key, value] of Object.entries(raw)) {
    if (Object.keys(prefs).length >= MAX_PREFS) break
    if (isDisplayPref(key, value)) prefs[key] = value
  }
  return prefs
}

/** *prefs* with *key* set, unless that would add a key beyond MAX_PREFS. */
export function withDisplayPref(prefs: DisplayPrefs, key: string, value: string): DisplayPrefs {
  if (!(key in prefs) && Object.keys(prefs).length >= MAX_PREFS) return prefs
  return { ...prefs, [key]: value }
}

export function sanitizeWindowColors(raw: unknown): WindowColors | null {
  if (!raw || typeof raw !== 'object') return null
  const { background, foreground } = raw as Record<string, unknown>
  if (typeof background !== 'string' || typeof foreground !== 'string') return null
  if (!HEX_COLOR.test(background) || !HEX_COLOR.test(foreground)) return null
  return { background: background.toLowerCase(), foreground: foreground.toLowerCase() }
}

/** Chromium's light/dark for every window, from the UI's theme choice: so the storage
 * window, loading page, native dialogs and scrollbars match the app. */
export function themeSourceFor(prefs: DisplayPrefs): ThemeSource {
  const theme = prefs[THEME_PREF_KEY]
  return theme === 'light' || theme === 'dark' ? theme : 'system'
}
