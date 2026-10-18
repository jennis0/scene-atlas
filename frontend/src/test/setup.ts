import '@testing-library/jest-dom/vitest'

// jsdom has no layout, so scroll APIs are missing.
Element.prototype.scrollTo ??= () => {}

// Nor ResizeObserver: a no-op is enough, since nothing has a size to report.
globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
}
