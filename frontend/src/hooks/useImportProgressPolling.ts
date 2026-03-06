import { useState, useEffect, useRef, useCallback } from 'react'
import { importApi } from '@/lib/api'
import type { ImportGroupStatus } from '@/types'

const POLL_INTERVAL_MS = 3000

interface UseImportProgressPollingOptions {
  importJobId: string | null | undefined
  onGroupCompleted: (groupId: number) => void
  enabled: boolean
  /** Set to true when the caller already knows the job is finished (e.g. status === 'completed').
   *  Prevents the brief "Processing (0 remaining…)" flash while the first poll response is in-flight. */
  initiallyDone?: boolean
}

interface UseImportProgressPollingReturn {
  runningGroups: ImportGroupStatus[]
  failedGroups: ImportGroupStatus[]
  allDone: boolean
  pollError: boolean
}

export function useImportProgressPolling({
  importJobId,
  onGroupCompleted,
  enabled,
  initiallyDone = false,
}: UseImportProgressPollingOptions): UseImportProgressPollingReturn {
  const [runningGroups, setRunningGroups] = useState<ImportGroupStatus[]>([])
  const [failedGroups, setFailedGroups] = useState<ImportGroupStatus[]>([])
  const [allDone, setAllDone] = useState(initiallyDone)
  const [pollError, setPollError] = useState(false)

  // Tracks which group_ids we've already notified about — prevents double-firing
  const notifiedGroupIds = useRef(new Set<number>())
  const onGroupCompletedRef = useRef(onGroupCompleted)
  onGroupCompletedRef.current = onGroupCompleted
  const initiallyDoneRef = useRef(initiallyDone)
  initiallyDoneRef.current = initiallyDone

  const poll = useCallback(async () => {
    if (!importJobId) return
    try {
      const status = await importApi.status(importJobId)
      setPollError(false)

      const running = status.groups.filter((g) => g.status === 'running')
      const failed = status.groups.filter((g) => g.status === 'failed' || g.status === 'cancelled')

      // Fire onGroupCompleted for any newly-completed groups
      for (const g of status.groups) {
        if (g.status === 'completed' && g.group_id && !notifiedGroupIds.current.has(g.group_id)) {
          notifiedGroupIds.current.add(g.group_id)
          onGroupCompletedRef.current(g.group_id)
        }
      }

      setRunningGroups(running)
      setFailedGroups(failed)
      setAllDone(running.length === 0)
    } catch {
      setPollError(true)
    }
  }, [importJobId])

  useEffect(() => {
    if (!enabled || !importJobId) {
      setRunningGroups([])
      setFailedGroups([])
      setAllDone(initiallyDoneRef.current)
      setPollError(false)
      notifiedGroupIds.current = new Set()
      return
    }

    // Immediate first fetch, then interval
    void poll()
    const id = setInterval(() => void poll(), POLL_INTERVAL_MS)
    return () => clearInterval(id)
  }, [enabled, importJobId, poll])

  return { runningGroups, failedGroups, allDone, pollError }
}
