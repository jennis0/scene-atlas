import { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from 'react'
import { isFinished } from '@/components/imports/format'
import { getImportManager } from '@/lib/import/ImportManager'

export interface SortedOut {
  /** Gallery group id → images Auto skipped from it (design/ingestion.md §5.6) */
  counts: Record<number, number>
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
  const finished = useFinishedJobs(pending.flatMap((p) => p.jobIds))

  useEffect(() => {
    if (!open) {
      setPending((p) => (p.length ? [] : p))
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
    const done = pending.filter((p) => p.jobIds.every((id) => finished.has(id)))
    if (done.length === 0) return
    setPending((prev) => prev.filter((p) => !done.includes(p)))
    const groupIds = [...new Set(done.map((p) => p.groupId))]
    mergeNewImages(groupIds)
      .catch(() => {}) // still there on the next open
      .finally(() => setVersion((v) => v + 1))
  }, [pending, finished, mergeNewImages])

  const included = useCallback((groupId: number, count: number, jobIds: string[]) => {
    setPending((prev) => [...prev, { groupId, count, jobIds }])
    setVersion((v) => v + 1)
  }, [])
  const importing = useMemo(() => {
    const byGroup: Record<number, number> = {}
    for (const p of pending) byGroup[p.groupId] = (byGroup[p.groupId] ?? 0) + p.count
    return byGroup
  }, [pending])
  return useMemo(() => ({ counts, importing, included }), [counts, importing, included])
}

const NOTHING_TO_WATCH = () => () => {}

/**
 * Which of `jobIds` have finished. Subscribes to the import manager only while there are
 * any, and re-renders only when the answer changes, not on every poll: the gallery keeps
 * its editors mounted. A job missing from the list counts as finished: the list holds
 * only recent imports, and `ImportManager.include` polls afresh before it returns, so a
 * job it re-opened is listed by then.
 */
function useFinishedJobs(jobIds: string[]): Set<string> {
  const manager = getImportManager()
  const key = [...new Set(jobIds)].sort().join(',')
  const subscribe = key ? manager.subscribe : NOTHING_TO_WATCH
  const getSnapshot = useCallback(() => {
    if (!key) return ''
    const { jobs } = manager.getSnapshot()
    return key
      .split(',')
      .filter((id) => {
        const job = jobs.find((j) => j.id === id)
        return job === undefined || isFinished(job)
      })
      .join(',')
  }, [key, manager])
  const finished = useSyncExternalStore(subscribe, getSnapshot)
  return useMemo(() => new Set(finished ? finished.split(',') : []), [finished])
}
