/**
 * Open dialogs, oldest first, sharing one window Escape listener that closes only the
 * topmost. Per-dialog listeners would close every open dialog at once (a ConfirmDialog
 * and the dialog under it), and their firing order shifts whenever one re-registers.
 */
type Close = () => void

const stack: Close[] = []

// An open Radix menu or popover dismisses itself on Escape (document listener, so it runs
// first) and should take that key alone. Its closing animation leaves it mounted with
// data-state="closed", which must not swallow the next Escape. defaultPrevented can't
// tell those apart, because Radix calls preventDefault either way.
const OPEN_RADIX_LAYER = '[data-radix-popper-content-wrapper] [data-state="open"]'

function onKeyDown(e: KeyboardEvent) {
  if (e.key !== 'Escape' || document.querySelector(OPEN_RADIX_LAYER)) return
  stack[stack.length - 1]?.()
}

/** Registers an open dialog; returns the unregister function. */
export function pushDialog(close: Close): () => void {
  if (stack.length === 0) window.addEventListener('keydown', onKeyDown)
  stack.push(close)
  return () => {
    const i = stack.lastIndexOf(close)
    if (i !== -1) stack.splice(i, 1)
    if (stack.length === 0) window.removeEventListener('keydown', onKeyDown)
  }
}

export const isAnyDialogOpen = () => stack.length > 0
