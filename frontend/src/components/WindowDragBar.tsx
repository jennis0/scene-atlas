import { isApp } from '@/lib/appMode'

/**
 * The desktop window has no title bar (design/electron.md#borderless-window), so a page
 * must mark where it can be dragged. This strip does it across the top of every screen
 * without the gallery header (which has its own): setup, loading, errors.
 *
 * It sits in the 32px band the Windows/Linux window controls already cover, which screens
 * keep clear of controls. Electron takes drag regions from element boxes, not hit testing,
 * so no z-index is needed and the page underneath is unaffected.
 */
export function WindowDragBar() {
  if (!isApp) return null
  return (
    <div
      aria-hidden="true"
      data-testid="window-drag-bar"
      className="fixed inset-x-0 top-0 h-8 drag-region"
    />
  )
}
