/**
 * A per-device display choice (palette, text size): saved in localStorage and set as a
 * data attribute on <html>, which index.css styles. The default sets no attribute, so
 * the base styles need no selector for it.
 */
export function displayChoice<T extends string>(
  storageKey: string,
  attribute: string,
  values: readonly T[],
  fallback: T,
) {
  /** The saved value; anything unknown (or unreadable storage) gives the default. */
  function read(): T {
    try {
      const stored = localStorage.getItem(storageKey)
      return values.find((v) => v === stored) ?? fallback
    } catch {
      return fallback
    }
  }

  function apply(value: T) {
    if (value === fallback) delete document.documentElement.dataset[attribute]
    else document.documentElement.dataset[attribute] = value
  }

  function save(value: T) {
    try {
      localStorage.setItem(storageKey, value)
    } catch {
      // Storage blocked (private mode, quota): the choice still applies for this session.
    }
    apply(value)
  }

  return { read, apply, save }
}
