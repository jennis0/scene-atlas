import { useState, useEffect } from 'react'
import { modelsApi } from '@/lib/api/modelsApi'

export type EmbeddingStatus = 'loading' | 'ready' | 'error'

interface UseEmbeddingStatusReturn {
  status: EmbeddingStatus
  error?: string
}

/**
 * Polls the embedding-status endpoint every 3 seconds while the model is loading.
 * Stops polling once the status becomes "ready" or "error".
 */
export function useEmbeddingStatus(): UseEmbeddingStatusReturn {
  const [status, setStatus] = useState<EmbeddingStatus>('loading')
  const [error, setError] = useState<string | undefined>(undefined)

  useEffect(() => {
    if (status !== 'loading') return

    let cancelled = false

    const check = async () => {
      try {
        const result = await modelsApi.embeddingStatus()
        if (cancelled) return
        const s = result.status as EmbeddingStatus
        setStatus(s)
        if (result.error) setError(result.error)
      } catch {
        // Network error during poll — keep trying
      }
    }

    // Initial check immediately
    check()

    const interval = setInterval(check, 3000)

    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [status])

  return { status, error }
}
