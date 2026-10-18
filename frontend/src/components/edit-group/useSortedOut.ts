import { useCallback, useEffect, useMemo, useState } from 'react'
import { isFinished } from '@/components/imports/format'
import { getImportManager } from '@/lib/import/ImportManager'
import { useImportManagerSnapshot } from '@/lib/import/useImports'

export interface SortedOut {
  /** Gallery group id → images Auto skipped from it (design/ingestion.md §5.6) */
  counts: Record<number, number>
  refresh: () => void
  /** Gallery group id → images included from it that are still being imported */
  importing: Record<number, number>
  /**
   * `count` images from `groupId` were included, re-opening these imports: once they
   * finish, the new images are merged into the loaded group and the counts re-read.
   */
  included: (groupId: number, count: number, jobIds: string[]) => void
}

interface PendingInclude {
  groupId: number
  count: number
  jobIds: string[]
}

/**
 * Images Auto skipped, per group: counts read when the editor opens and after an include,
 * and included images brought into the open editor once they're imported. Auxiliary: if
 * the server can't be reached the counts stay empty and the editor works as before.
 */
export function useSortedOut(
  open: boolean,
  mergeNewImages: (groupIds: number[]) => Promise<void>,
): SortedOut {
  const [counts, setCounts] = useState<Record<number, number>>({})
  const [version, setVersion] = useState(0)
  const [pending, setPending] = useState<PendingInclude[]>([])
  const { jobs } = useImportManagerSnapshot()

  useEffect(() => {
    if (!open) {
      setPending([])
      return
    }
    let cancelled = false
    getImportManager()
      .sortedOutCounts()
      .then((c) => !cancelled && setCounts(c))
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [open, version])

  // Merge each include's group once every import it re-opened has finished
  useEffect(() => {
    const done = pending.filter((p) =>
      p.jobIds.every((id) => {
        const job = jobs.find((j) => j.id === id)
        return job !== undefined && isFinished(job)
      }),
    )
    if (done.length === 0) return
    setPending((prev) => prev.filter((p) => !done.includes(p)))
    const groupIds = [...new Set(done.map((p) => p.groupId))]
    mergeNewImages(groupIds)
      .catch(() => {}) // still there on the next open
      .finally(() => setVersion((v) => v + 1))
  }, [pending, jobs, mergeNewImages])

  const refresh = useCallback(() => setVersion((v) => v + 1), [])
  const included = useCallback((groupId: number, count: number, jobIds: string[]) => {
    setPending((prev) => [...prev, { groupId, count, jobIds }])
    setVersion((v) => v + 1)
  }, [])
  const importing = useMemo(() => {
    const byGroup: Record<number, number> = {}
    for (const p of pending) byGroup[p.groupId] = (byGroup[p.groupId] ?? 0) + p.count
    return byGroup
  }, [pending])
  return { counts, refresh, importing, included }
}
