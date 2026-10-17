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
  // Consume the key: an Escape that cancels an edit must not also close the enclosing
  // Dialog (its window listener skips default-prevented events, and stopPropagation keeps
  // the key from reaching window at all), and Enter must not reach parent key handlers.
  e.preventDefault()
  e.stopPropagation()
  handler()
}
