import { readPref, registerPref, writePref } from './prefsStorage'

/**
 * A per-device display choice (palette, text size): saved as a preference (prefsStorage)
 * and set as a data attribute on <html>, which index.css styles. The default sets no attribute, so
 * the base styles need no selector for it.
 */

export function displayChoice<T extends string>(
  storageKey: string,
  attribute: string,
  values: readonly T[],
  fallback: T,
) {
  registerPref(storageKey)

  /** The saved value; anything unknown (or unreadable storage) gives the default. */
  function read(): T {
    const stored = readPref(storageKey)
    return values.find((v) => v === stored) ?? fallback
  }

  function apply(value: T) {
    if (value === fallback) delete document.documentElement.dataset[attribute]
    else document.documentElement.dataset[attribute] = value
  }

  function save(value: T) {
    writePref(storageKey, value)
    apply(value)
  }

  return { read, apply, save }
}

export type DisplayChoice<T extends string> = ReturnType<typeof displayChoice<T>>
