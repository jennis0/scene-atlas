import { ExternalLink } from 'lucide-react'
import { MODEL_COLLECTION_URL } from '@/lib/modelConstants'

/** Link to the published models on Hugging Face (opens in the browser in the desktop app). */
export function AboutModelsLink() {
  return (
    <a
      href={MODEL_COLLECTION_URL}
      target="_blank"
      rel="noopener noreferrer"
      className="inline-flex items-center gap-1 text-xs text-muted-foreground underline underline-offset-2 hover:text-foreground"
    >
      About these models
      <ExternalLink aria-hidden="true" className="h-3 w-3" />
      <span className="sr-only">(opens on Hugging Face)</span>
    </a>
  )
}
