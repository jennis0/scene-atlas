/** "rgb(14, 17, 24)" (a computed colour) as "#0e1118"; null if transparent or unparseable. */
export function cssColorToHex(css: string): string | null {
  const match = /^rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?\)$/.exec(css.trim())
  if (!match) return null
  if (match[4] !== undefined && Number(match[4]) < 1) return null
  return `#${match
    .slice(1, 4)
    .map((n) => Number(n).toString(16).padStart(2, '0'))
    .join('')}`
}

/** Desktop only: give the window the page's background and text colours, for its own
 * background and the Windows/Linux title-bar controls (design/first-run.md). */
export function reportWindowColors() {
  const api = window.electronAPI
  if (!api?.setWindowColors) return
  const style = getComputedStyle(document.body)
  const background = cssColorToHex(style.backgroundColor)
  const foreground = cssColorToHex(style.color)
  if (background && foreground) void api.setWindowColors({ background, foreground }).catch(() => {})
}
