/**
 * Open dialogs, oldest first, sharing one window Escape listener that closes only the
 * topmost. Per-dialog listeners would close every open dialog at once (a ConfirmDialog
 * and the dialog under it), and their firing order shifts whenever one re-registers.
 */
type Close = () => void

const stack: Close[] = []

function onKeyDown(e: KeyboardEvent) {
  // defaultPrevented: something inside already handled it (e.g. cancelled an inline edit).
  if (e.key !== 'Escape' || e.defaultPrevented) return
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
