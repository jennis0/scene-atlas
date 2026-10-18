/**
 * Light/dark theme. The saved preference may be System, which follows the OS setting
 * live; consumers mostly want the resolved theme. Dark mode is the `dark` class on <html>
 * (Tailwind darkMode: "class"). See design/first-run.md.
 */
import { readPref, registerPref, writePref } from './prefsStorage'

export type Theme = 'light' | 'dark'
export type ThemePreference = 'system' | Theme

export const THEME_OPTIONS: readonly { value: ThemePreference; label: string; title: string }[] = [
  { value: 'system', label: 'System', title: "Follow your system's light or dark setting" },
  { value: 'light', label: 'Light', title: 'Light mode' },
  { value: 'dark', label: 'Dark', title: 'Dark mode' },
]

export const THEME_STORAGE_KEY = 'scene-atlas-theme'
registerPref(THEME_STORAGE_KEY)

const systemDarkQuery = () => window.matchMedia?.('(prefers-color-scheme: dark)')

/** The saved preference; nothing saved (or unreadable storage) means System. */
export function readThemePreference(): ThemePreference {
  const stored = readPref(THEME_STORAGE_KEY)
  return THEME_OPTIONS.find((o) => o.value === stored)?.value ?? 'system'
}

export function saveThemePreference(preference: ThemePreference) {
  writePref(THEME_STORAGE_KEY, preference)
}

/** System resolves to the OS setting, or dark (the app's original look) when unknown. */
export function resolveTheme(preference: ThemePreference): Theme {
  if (preference !== 'system') return preference
  const query = systemDarkQuery()
  return !query || query.matches ? 'dark' : 'light'
}

export function applyTheme(theme: Theme) {
  document.documentElement.classList.toggle('dark', theme === 'dark')
}

/** Calls *onChange* when the OS switches between light and dark. Returns the unsubscribe. */
export function watchSystemTheme(onChange: () => void): () => void {
  const query = systemDarkQuery()
  query?.addEventListener?.('change', onChange)
  return () => query?.removeEventListener?.('change', onChange)
}
