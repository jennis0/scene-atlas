import { MARK_BANDS, MARK_PAGES, MARK_VIEWBOX } from './markPaths'

/**
 * The Scene Atlas mark, drawn in the active theme: the pages take the text colour and
 * the base band the accent, so it follows palette, light/dark and contrast. Decorative:
 * it always sits beside the "Scene Atlas" wordmark, which carries the name.
 */
export function BrandMark({ className }: { className?: string }) {
  return (
    <svg viewBox={MARK_VIEWBOX} className={className} aria-hidden="true" focusable="false">
      {MARK_BANDS.map((d) => (
        <path key={d} d={d} className="fill-primary" />
      ))}
      {MARK_PAGES.map((d) => (
        <path key={d} d={d} className="fill-mark-page" />
      ))}
    </svg>
  )
}
