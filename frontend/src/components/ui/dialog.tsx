import * as React from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'
import { cn } from '@/lib/utils'

interface DialogProps {
  open?: boolean
  onOpenChange?: (open: boolean) => void
  children?: React.ReactNode
}

const Dialog = ({ open, onOpenChange, children }: DialogProps) => {
  const containerRef = React.useRef<HTMLDivElement>(null)

  React.useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && open) {
        onOpenChange?.(false)
      }
    }
    window.addEventListener('keydown', handleEscape)
    return () => window.removeEventListener('keydown', handleEscape)
  }, [open, onOpenChange])

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

    // Guard: if focus leaves the dialog container, reclaim it
    const onFocusOut = (e: FocusEvent) => {
      const next = e.relatedTarget as Node | null
      if (!next || !el.contains(next)) {
        queueMicrotask(() => findTarget()?.focus())
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
>(({ className, children, onClose, ...props }, ref) => (
  <div
    ref={ref}
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
        className="absolute right-4 top-4 h-7 w-7 rounded flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors focus:outline-none focus-visible:ring-1 focus-visible:ring-primary/40"
      >
        <X className="h-3.5 w-3.5" />
        <span className="sr-only">Close</span>
      </button>
    )}
  </div>
))
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
    className={cn('text-lg font-semibold leading-none tracking-tight', className)}
    {...props}
  />
))
DialogTitle.displayName = 'DialogTitle'

export { Dialog, DialogContent, DialogHeader, DialogTitle }
