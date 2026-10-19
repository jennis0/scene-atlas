import { useState, useEffect } from 'react'
import { modelsApi, type EmbeddingStatus } from '@/lib/api/modelsApi'

interface UseEmbeddingStatusReturn {
  status: EmbeddingStatus
  /** Why the model isn't ready, for the UI */
  message?: string
}

/** Statuses that can still turn into "ready" without a reload (a download from Settings). */
const POLLED: ReadonlySet<EmbeddingStatus> = new Set(['loading', 'missing'])

/**
 * Polls the embedding-status endpoint every 3 seconds until the model is ready or has
 * failed to load.
 */
export function useEmbeddingStatus(): UseEmbeddingStatusReturn {
  const [status, setStatus] = useState<EmbeddingStatus>('loading')
  const [message, setMessage] = useState<string | undefined>(undefined)

  useEffect(() => {
    if (!POLLED.has(status)) return

    let cancelled = false

    const check = async () => {
      try {
        const result = await modelsApi.embeddingStatus()
        if (cancelled) return
        setStatus(result.status)
        setMessage(result.message ?? undefined)
      } catch {
        // Network error during poll — keep trying
      }
    }

    check()

    const interval = setInterval(check, 3000)

    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [status])

  return { status, message }
}
