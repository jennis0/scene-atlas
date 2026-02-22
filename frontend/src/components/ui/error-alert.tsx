import { AlertCircle, X } from 'lucide-react'

interface ErrorAlertProps {
  message: string
  onDismiss?: () => void
  className?: string
}

/**
 * Inline error alert for displaying API or validation errors within a form or dialog.
 * Use instead of ad-hoc error rendering to keep error UI consistent.
 */
export function ErrorAlert({ message, onDismiss, className = '' }: ErrorAlertProps) {
  return (
    <div
      role="alert"
      className={`flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive ${className}`}
    >
      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
      <span className="flex-1">{message}</span>
      {onDismiss && (
        <button
          onClick={onDismiss}
          aria-label="Dismiss error"
          className="shrink-0 rounded opacity-70 hover:opacity-100 transition-opacity"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      )}
    </div>
  )
}
