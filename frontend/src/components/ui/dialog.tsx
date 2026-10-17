import * as React from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'
import { cn } from '@/lib/utils'
import { pushDialog } from './dialogStack'
import { useModalLayer } from './modalLayer'
import { DialogTitleIdContext } from './dialogTitleId'

interface DialogProps {
  open?: boolean
  onOpenChange?: (open: boolean) => void
  children?: React.ReactNode
}

const Dialog = ({ open, onOpenChange, children }: DialogProps) => {
  const containerRef = React.useRef<HTMLDivElement>(null)
  const onOpenChangeRef = React.useRef(onOpenChange)
  onOpenChangeRef.current = onOpenChange

  // Layout effect: a passive cleanup can run after the dialog has left the DOM, and an
  // Escape in that gap would go to this dead entry instead of the dialog underneath.
  React.useLayoutEffect(() => {
    if (open) return pushDialog(() => onOpenChangeRef.current?.(false))
  }, [open])

  // Inert the rest of the page while open, and return focus to the opener on close.
  useModalLayer(containerRef, !!open)

  // Move focus into the dialog when it opens. Looks for an element marked with
  // data-autofocus first, then falls back to the first focusable element.
  // Uses a microtask so the DOM is settled after React's StrictMode double-mount.
  // A brief focusout guard re-asserts focus if an external element (e.g. a closing
  // Radix dropdown) steals it during the open transition.
  React.useEffect(() => {
    if (!open) return
    const el = containerRef.current
    if (!el) return

    const findTarget = () =>
      el.querySelector<HTMLElement>('[data-autofocus]') ??
      el.querySelector<HTMLElement>(
        'input:not([disabled]):not([type="hidden"]), textarea:not([disabled]), select:not([disabled]), button:not([disabled]), [tabindex]:not([tabindex="-1"])',
      )

    // Guard: if focus leaves the dialog container, reclaim it.
    // Uses setTimeout instead of queueMicrotask to avoid starving the event
    // loop when relatedTarget is null (e.g. jsdom), which would prevent the
    // guardTimer cleanup from ever firing.
    const onFocusOut = (e: FocusEvent) => {
      const next = e.relatedTarget as Node | null
      if (!next || !el.contains(next)) {
        setTimeout(() => findTarget()?.focus(), 0)
      }
    }
    el.addEventListener('focusout', onFocusOut)
    const guardTimer = setTimeout(() => el.removeEventListener('focusout', onFocusOut), 500)

    queueMicrotask(() => findTarget()?.focus())

    return () => {
      el.removeEventListener('focusout', onFocusOut)
      clearTimeout(guardTimer)
    }
  }, [open])

  if (!open) return null

  return createPortal(
    <div
      ref={containerRef}
      className="fixed inset-0 z-50 flex items-center justify-center"
      onClick={(e) => e.stopPropagation()}
    >
      <div className="fixed inset-0 bg-black/80" onClick={() => onOpenChange?.(false)} />
      {children}
    </div>,
    document.body,
  )
}

const DialogContent = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement> & { onClose?: () => void }
>(({ className, children, onClose, ...props }, ref) => {
  // Named by the title rendered inside, unless the caller names it another way.
  const titleId = React.useId()
  const named = props['aria-label'] !== undefined || props['aria-labelledby'] !== undefined
  return (
    <DialogTitleIdContext.Provider value={named ? undefined : titleId}>
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby={named ? undefined : titleId}
        className={cn(
          'relative z-50 grid w-full max-w-lg gap-4 border bg-background p-6 shadow-lg sm:rounded-lg',
          className,
        )}
        {...props}
      >
        {children}
        {onClose && (
          <button
            onClick={onClose}
            className="absolute right-4 top-4 h-7 w-7 rounded flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors"
          >
            <X className="h-3.5 w-3.5" />
            <span className="sr-only">Close</span>
          </button>
        )}
      </div>
    </DialogTitleIdContext.Provider>
  )
})
DialogContent.displayName = 'DialogContent'

const DialogHeader = ({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) => (
  <div className={cn('flex flex-col space-y-1.5 text-center sm:text-left', className)} {...props} />
)
DialogHeader.displayName = 'DialogHeader'

const DialogTitle = React.forwardRef<
  HTMLParagraphElement,
  React.HTMLAttributes<HTMLHeadingElement>
>(({ className, ...props }, ref) => (
  <h2
    ref={ref}
    id={React.useContext(DialogTitleIdContext)}
    className={cn('text-lg font-semibold leading-none tracking-tight', className)}
    {...props}
  />
))
DialogTitle.displayName = 'DialogTitle'

export { Dialog, DialogContent, DialogHeader, DialogTitle }
