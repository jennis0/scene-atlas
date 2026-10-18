/**
 * Per-device preferences (display choices), kept in localStorage. In the desktop app,
 * localStorage belongs to the backend's origin, which changes with its port, so the app
 * config keeps a copy and is the source of truth at startup (design/first-run.md).
 */

/** Keys kept here: the ones synced with the desktop config */
const registered = new Set<string>()

const desktop = () => (typeof window === 'undefined' ? undefined : window.electronAPI)

/** Declare a key as a preference; call at module load, before syncPrefsWithDesktop(). */
export function registerPref(key: string) {
  registered.add(key)
}

export function readPref(key: string): string | null {
  try {
    const value = localStorage.getItem(key)
    if (value !== null) return value
  } catch {
    // Storage blocked: fall through to the desktop copy, if any
  }
  return desktop()?.displayPrefs?.[key] ?? null
}

export function writePref(key: string, value: string) {
  try {
    localStorage.setItem(key, value)
  } catch {
    // Storage blocked (private mode, quota): the choice still applies for this session.
  }
  desktop()
    ?.setDisplayPref?.(key, value)
    .catch(() => {
      // The config copy catches up on the next change
    })
}

/**
 * Desktop only; call once at startup, before reading preferences. The config's values
 * replace localStorage's, which may be another port's or stale. Values only in localStorage
 * (saved before the config kept them) are copied into the config, so nobody's choices reset.
 */
export function syncPrefsWithDesktop() {
  const api = desktop()
  if (!api?.displayPrefs) return
  try {
    for (const key of registered) {
      const saved = api.displayPrefs[key]
      if (saved !== undefined) {
        localStorage.setItem(key, saved)
      } else {
        const local = localStorage.getItem(key)
        if (local !== null) void api.setDisplayPref(key, local).catch(() => {})
      }
    }
  } catch {
    // Storage blocked: readPref falls back to the desktop copy
  }
}
