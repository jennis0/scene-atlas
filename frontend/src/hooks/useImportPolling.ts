import { useEffect } from 'react'
import { importApi } from '@/lib/api'
import { POLL_INTERVAL_MS } from '@/lib/constants'
import type { EditableGroupState } from '@/types'
import type { DialogState } from './useImportState'

interface UseImportPollingOptions {
  state: DialogState
  jobId: string | null
  setGroups: React.Dispatch<React.SetStateAction<EditableGroupState[]>>
  setState: (state: DialogState) => void
}

/** Polls the backend for job status while state === 'processing'. */
export function useImportPolling({
  state,
  jobId,
  setGroups,
  setState,
}: UseImportPollingOptions): void {
  useEffect(() => {
    if (state !== 'processing' || !jobId) return
    const poll = async () => {
      try {
        const status = await importApi.status(jobId)
        let hasPendingLocally = false
        setGroups((prev) => {
          const next = prev.map((g) => {
            const gs = status.groups.find((s) => s.group_name === g.group_name)
            if (!gs) return g
            return {
              ...g,
              status: gs.status as EditableGroupState['status'],
              processed: gs.processed_files,
              failed: gs.failed_files,
              total: gs.total_files || g.total,
            }
          })
          hasPendingLocally = next.some((g) => g.status === 'pending')
          return next
        })
        const allSubmittedDone =
          status.groups.length > 0 &&
          status.groups.every((gs) => gs.status === 'completed' || gs.status === 'failed')
        if (allSubmittedDone) {
          // Check both local state and backend-derived pending count
          const backendHasPending = (status.pending_group_count ?? 0) > 0
          setState(hasPendingLocally || backendHasPending ? 'preview' : 'done')
        }
      } catch {
        /* ignore transient poll errors */
      }
    }
    poll()
    const interval = setInterval(poll, POLL_INTERVAL_MS)
    return () => clearInterval(interval)
  }, [state, jobId, setGroups, setState])
}
