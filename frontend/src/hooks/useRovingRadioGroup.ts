import { useRef, type KeyboardEvent } from 'react'

const NEXT_KEYS = ['ArrowRight', 'ArrowDown']
const PREV_KEYS = ['ArrowLeft', 'ArrowUp']

/**
 * Keyboard behaviour for a group of `role="radio"` buttons (WAI-ARIA radio group): one tab
 * stop, the checked option (or the first, when none is); arrow keys move and select,
 * wrapping; Home and End jump to the ends. Spread `itemProps(index)` on each button: it
 * sets the role, checked state, click and keyboard handling.
 */
export function useRovingRadioGroup<T>(
  values: readonly T[],
  value: T,
  onChange: (value: T) => void,
) {
  const buttons = useRef<(HTMLButtonElement | null)[]>([])
  const checkedIndex = values.indexOf(value)

  const select = (index: number) => {
    onChange(values[index])
    buttons.current[index]?.focus()
  }

  const onKeyDown = (event: KeyboardEvent, index: number) => {
    const last = values.length - 1
    let next: number | null = null
    if (NEXT_KEYS.includes(event.key)) next = index === last ? 0 : index + 1
    else if (PREV_KEYS.includes(event.key)) next = index === 0 ? last : index - 1
    else if (event.key === 'Home') next = 0
    else if (event.key === 'End') next = last
    if (next === null) return
    event.preventDefault()
    select(next)
  }

  return (index: number) => ({
    ref: (el: HTMLButtonElement | null) => {
      buttons.current[index] = el
    },
    type: 'button' as const,
    role: 'radio',
    'aria-checked': index === checkedIndex,
    tabIndex: index === (checkedIndex === -1 ? 0 : checkedIndex) ? 0 : -1,
    onClick: () => onChange(values[index]),
    onKeyDown: (event: KeyboardEvent) => onKeyDown(event, index),
  })
}
