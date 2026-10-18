import { useCallback, useEffect, useState } from 'react'
import { getImportManager } from '@/lib/import/ImportManager'

export interface SortedOutCounts {
  /** Gallery group id → images Auto skipped from it (design/ingestion.md §5.6) */
  counts: Record<number, number>
  refresh: () => void
}

/**
 * How many images Auto skipped from each group, read once when the editor opens and
 * again after an include. Auxiliary: if the server can't be reached the counts stay
 * empty and the editor works as before.
 */
export function useSortedOutCounts(open: boolean): SortedOutCounts {
  const [counts, setCounts] = useState<Record<number, number>>({})
  const [version, setVersion] = useState(0)

  useEffect(() => {
    if (!open) return
    let cancelled = false
    getImportManager()
      .sortedOutCounts()
      .then((c) => !cancelled && setCounts(c))
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [open, version])

  const refresh = useCallback(() => setVersion((v) => v + 1), [])
  return { counts, refresh }
}
