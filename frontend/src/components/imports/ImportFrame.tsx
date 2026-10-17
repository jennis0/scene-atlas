/**
 * Shared chrome for the import dialogs: amber stripe, Cinzel title with a
 * one-line status beneath it, close button, and a footer bar.
 */

import { useId, type ReactNode } from 'react'
import { X } from 'lucide-react'
import { Dialog, DialogContent } from '@/components/ui/dialog'

interface ImportFrameProps {
  open: boolean
  onClose: () => void
  title: ReactNode
  status?: ReactNode
  width?: 'md' | 'lg'
  children: ReactNode
  footer?: ReactNode
}

export function ImportFrame({
  open,
  onClose,
  title,
  status,
  width = 'md',
  children,
  footer,
}: ImportFrameProps) {
  const titleId = useId()
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className={`${width === 'lg' ? 'max-w-3xl h-[82vh]' : 'max-w-xl max-h-[82vh]'} flex flex-col p-0 gap-0 overflow-hidden bg-card border-border/40 rounded-lg shadow-2xl shadow-black/70`}
      >
        <header className="flex items-start justify-between gap-4 px-6 pt-5 pb-3 shrink-0">
          <div className="min-w-0">
            <h2
              id={titleId}
              className="font-display text-lg font-semibold text-foreground truncate"
            >
              {title}
            </h2>
            {status && <div className="mt-2 text-xs text-muted-foreground">{status}</div>}
          </div>
          <button
            onClick={onClose}
            className="h-7 w-7 shrink-0 rounded flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors"
          >
            <X className="h-3.5 w-3.5" />
            <span className="sr-only">Close</span>
          </button>
        </header>

        {/* Scrolls when the window is short (zoomed in, large text); views with their own
            scrolling list fill it exactly and never trigger this */}
        <div className="relative flex-1 min-h-0 flex flex-col overflow-y-auto">{children}</div>

        {footer && (
          <footer className="shrink-0 flex flex-wrap items-center gap-2 px-6 py-3 border-t border-border/30 bg-popover">
            {footer}
          </footer>
        )}
      </DialogContent>
    </Dialog>
  )
}

/** Ghost text button used in footers and banners. */
export function TextButton({
  children,
  onClick,
  tone = 'default',
  disabled,
  title,
}: {
  children: ReactNode
  onClick: () => void
  /** solid: the dialog's one main next step; outline: a footer control */
  tone?: 'default' | 'primary' | 'solid' | 'danger' | 'outline' | 'outline-danger'
  disabled?: boolean
  title?: string
}) {
  const toneClass =
    tone === 'solid'
      ? 'bg-primary text-primary-foreground hover:bg-primary/85 border-transparent font-medium'
      : tone === 'outline'
        ? 'text-foreground border-border hover:bg-secondary'
        : tone === 'outline-danger'
          ? 'text-foreground border-border hover:text-destructive hover:border-destructive/40 hover:bg-destructive/10'
          : tone === 'primary'
            ? 'text-primary bg-primary/10 hover:bg-primary/20 border-primary/25'
            : tone === 'danger'
              ? 'text-muted-foreground hover:text-destructive hover:bg-destructive/10 border-transparent'
              : 'text-muted-foreground hover:text-foreground hover:bg-secondary border-transparent'
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={`inline-flex items-center gap-1.5 h-8 px-3 rounded-md border text-xs whitespace-nowrap transition-colors disabled:opacity-30 disabled:cursor-not-allowed ${toneClass}`}
    >
      {children}
    </button>
  )
}

/** Inline confirmation over the dialog body (visual-language "confirm overlay"). */
export function ConfirmOverlay({
  title,
  detail,
  confirmLabel,
  tone,
  busy,
  onConfirm,
  onCancel,
}: {
  title: string
  detail: ReactNode
  confirmLabel: string
  tone: 'warning' | 'danger'
  busy?: boolean
  onConfirm: () => void
  onCancel: () => void
}) {
  const confirmClass =
    tone === 'danger'
      ? 'text-destructive bg-destructive/10 hover:bg-destructive/20 border-destructive/20'
      : 'text-primary bg-primary/10 hover:bg-primary/20 border-primary/20'
  return (
    <div className="absolute inset-0 z-10 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div
        role="alertdialog"
        aria-label={title}
        className="bg-card border border-border rounded-lg p-5 max-w-sm mx-4 shadow-2xl shadow-black/70"
      >
        <p className="text-sm font-semibold text-foreground">{title}</p>
        <div className="mt-1.5 text-xs text-muted-foreground leading-relaxed">{detail}</div>
        <div className="mt-4 flex justify-end gap-2">
          <TextButton onClick={onCancel}>Keep it</TextButton>
          <button
            onClick={onConfirm}
            disabled={busy}
            data-autofocus
            className={`h-8 px-3 rounded-md border text-xs transition-colors disabled:opacity-40 ${confirmClass}`}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}

/** A one-line notice inside a dialog: attention (amber) or problem (red). */
export function Notice({
  tone,
  icon,
  children,
  actions,
}: {
  tone: 'attention' | 'problem'
  icon: ReactNode
  children: ReactNode
  actions?: ReactNode
}) {
  const toneClass =
    tone === 'attention'
      ? 'border-primary/25 bg-primary/[0.06] text-foreground'
      : 'border-destructive/30 bg-destructive/[0.07] text-foreground'
  return (
    <div className={`flex items-start gap-2.5 rounded-lg border px-3 py-2.5 ${toneClass}`}>
      <span className={tone === 'attention' ? 'text-primary mt-px' : 'text-destructive mt-px'}>
        {icon}
      </span>
      <div className="flex-1 min-w-0">
        <div className="text-xs leading-relaxed">{children}</div>
        {actions && <div className="mt-1.5 -ml-3 flex flex-wrap items-center gap-1">{actions}</div>}
      </div>
    </div>
  )
}
