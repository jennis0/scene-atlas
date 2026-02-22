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
        setGroups((prev) =>
          prev.map((g) => {
            const gs = status.groups.find((s) => s.group_name === g.group_name)
            if (!gs) return g
            return {
              ...g,
              status: gs.status as EditableGroupState['status'],
              processed: gs.processed_files,
              failed: gs.failed_files,
              total: gs.total_files || g.total,
            }
          }),
        )
        if (
          status.groups.length > 0 &&
          status.groups.every((gs) => gs.status === 'completed' || gs.status === 'failed')
        ) {
          setState('done')
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
