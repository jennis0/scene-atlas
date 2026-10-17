import { useEffect, type RefObject } from 'react'

/** Body children marked with this attribute stay interactive under a modal (e.g. toasts). */
export const MODAL_EXEMPT_ATTR = 'data-modal-exempt'

/**
 * Where focus should go when a modal closes. Usually the element focused when it opened.
 * A modal opened from a Radix menu item would otherwise lose focus to <body>, because the
 * item unmounts with its menu; the menu's trigger is named by the menu's aria-labelledby.
 */
function returnTarget(): HTMLElement | null {
  const active = document.activeElement as HTMLElement | null
  if (!active || active === document.body) return null
  const menu = active.closest('[role="menu"]')
  const triggerId = menu?.getAttribute('aria-labelledby')
  return (triggerId && document.getElementById(triggerId)) || active
}

/**
 * Makes the element a modal layer while `active`: every other child of <body> becomes
 * `inert` (unfocusable, unclickable, hidden from assistive tech), and focus returns to
 * where it was when the layer closes.
 *
 * The element must be portalled to <body> (directly or as a descendant of a body child),
 * so the app root can go inert without taking the modal with it. Radix popovers opened
 * from inside the modal portal to <body> after this runs, so they stay interactive.
 * Nested modals work as a stack: each one inerts what is beneath it and restores only
 * the attributes it set.
 */
export function useModalLayer(ref: RefObject<HTMLElement>, active: boolean) {
  useEffect(() => {
    if (!active) return
    const el = ref.current
    if (!el) return

    const restoreFocusTo = returnTarget()

    let layer: HTMLElement = el
    while (layer.parentElement && layer.parentElement !== document.body) {
      layer = layer.parentElement
    }

    const inerted: Element[] = []
    for (const child of Array.from(document.body.children)) {
      if (
        child === layer ||
        child.hasAttribute('inert') ||
        child.hasAttribute(MODAL_EXEMPT_ATTR) ||
        child.tagName === 'SCRIPT' ||
        child.tagName === 'STYLE'
      )
        continue
      child.setAttribute('inert', '')
      inerted.push(child)
    }

    return () => {
      for (const child of inerted) child.removeAttribute('inert')
      if (restoreFocusTo?.isConnected) restoreFocusTo.focus({ preventScroll: true })
    }
  }, [ref, active])
}
