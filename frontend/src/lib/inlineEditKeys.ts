import type { KeyboardEvent } from 'react'

interface InlineEditKeyHandlers {
  onEnter?: () => void
  onEscape?: () => void
  /** Let Shift+Enter through (a newline in a textarea). */
  allowShiftEnter?: boolean
}

/** Enter commits and Escape cancels an inline edit. */
export function onInlineEditKey(
  e: KeyboardEvent<HTMLElement>,
  { onEnter, onEscape, allowShiftEnter = false }: InlineEditKeyHandlers,
) {
  const handler =
    e.key === 'Enter' && !(allowShiftEnter && e.shiftKey)
      ? onEnter
      : e.key === 'Escape'
        ? onEscape
        : undefined
  if (!handler) return
  // Consume the key: stopPropagation keeps an Escape that cancels an edit from reaching
  // the Dialog's window listener, and Enter from reaching parent key handlers.
  e.preventDefault()
  e.stopPropagation()
  handler()
}
