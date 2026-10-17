import '@testing-library/jest-dom'

// jsdom has no layout, so scroll APIs are missing.
Element.prototype.scrollTo ??= () => {}
