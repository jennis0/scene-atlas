import { AlertCircle, Loader2 } from 'lucide-react'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import type { EmbeddingStatus } from '@/lib/api/modelsApi'

function problemLabel(status: EmbeddingStatus): string | null {
  switch (status) {
    case 'missing':
      return 'Search model not downloaded'
    case 'error':
      return 'Search model unavailable'
    default:
      return null
  }
}

const PILL =
  'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium shrink-0'

interface SearchModelStatusProps {
  status: EmbeddingStatus
  /** The backend's explanation (never an exception's text) */
  message?: string
}

/** Why searching by description isn't available yet; nothing once the model is ready. */
export function SearchModelStatus({ status, message }: SearchModelStatusProps) {
  if (status === 'loading') {
    return (
      <span role="status" className={`${PILL} bg-warning/15 text-warning`}>
        <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />
        Search model loading&hellip;
      </span>
    )
  }

  const label = problemLabel(status)
  if (!label) return null
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          className={`${PILL} bg-destructive/15 text-destructive hover:bg-destructive/25 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring`}
        >
          <AlertCircle className="h-3 w-3" aria-hidden="true" />
          {label}
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="text-sm leading-relaxed">
        {message ?? 'Searching by description is unavailable.'}
      </PopoverContent>
    </Popover>
  )
}
