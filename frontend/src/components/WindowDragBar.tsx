import { isFrameless, TITLE_BAR_BAND } from '@/lib/appMode'

/**
 * The desktop window has no title bar on Windows and macOS (design/electron.md#window-frame),
 * so a page must mark where it can be dragged. This strip does it across the top of every
 * screen without the gallery header (which has its own): setup, loading, errors.
 *
 * It sits in the 32px band the Windows window controls already cover, which screens keep
 * clear of controls. Electron takes drag regions from element boxes, not hit testing, so no
 * z-index is needed and the page underneath is unaffected.
 */
export function WindowDragBar() {
  if (!isFrameless) return null
  return (
    <div
      aria-hidden="true"
      data-testid="window-drag-bar"
      className={`fixed inset-x-0 top-0 ${TITLE_BAR_BAND} drag-region`}
    />
  )
}
