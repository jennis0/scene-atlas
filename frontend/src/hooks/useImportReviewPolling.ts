import { useState, useEffect, useRef, useCallback } from 'react'
import { importApi } from '@/lib/api'
import type { ImportGroupStatus } from '@/types'

const POLL_INTERVAL_MS = 3000

interface UseImportReviewPollingOptions {
  importJobId: string | null | undefined
  onGroupCompleted: (groupId: number) => void
  enabled: boolean
}

interface UseImportReviewPollingReturn {
  pendingGroups: ImportGroupStatus[]
  failedGroups: ImportGroupStatus[]
  allDone: boolean
  pollError: boolean
}

export function useImportReviewPolling({
  importJobId,
  onGroupCompleted,
  enabled,
}: UseImportReviewPollingOptions): UseImportReviewPollingReturn {
  const [pendingGroups, setPendingGroups] = useState<ImportGroupStatus[]>([])
  const [failedGroups, setFailedGroups] = useState<ImportGroupStatus[]>([])
  const [allDone, setAllDone] = useState(false)
  const [pollError, setPollError] = useState(false)

  // Tracks which group_ids we've already notified about — prevents double-firing
  const notifiedGroupIds = useRef(new Set<number>())
  const onGroupCompletedRef = useRef(onGroupCompleted)
  onGroupCompletedRef.current = onGroupCompleted

  const poll = useCallback(async () => {
    if (!importJobId) return
    try {
      const status = await importApi.status(importJobId)
      setPollError(false)

      const pending = status.groups.filter((g) => g.status === 'running')
      const failed = status.groups.filter((g) => g.status === 'failed' || g.status === 'cancelled')

      // Fire onGroupCompleted for any newly-completed groups
      for (const g of status.groups) {
        if (g.status === 'completed' && g.group_id && !notifiedGroupIds.current.has(g.group_id)) {
          notifiedGroupIds.current.add(g.group_id)
          onGroupCompletedRef.current(g.group_id)
        }
      }

      setPendingGroups(pending)
      setFailedGroups(failed)
      setAllDone(pending.length === 0)
    } catch {
      setPollError(true)
    }
  }, [importJobId])

  useEffect(() => {
    if (!enabled || !importJobId) {
      setPendingGroups([])
      setFailedGroups([])
      setAllDone(false)
      setPollError(false)
      notifiedGroupIds.current = new Set()
      return
    }

    // Immediate first fetch, then interval
    void poll()
    const id = setInterval(() => void poll(), POLL_INTERVAL_MS)
    return () => clearInterval(id)
  }, [enabled, importJobId, poll])

  return { pendingGroups, failedGroups, allDone, pollError }
}
