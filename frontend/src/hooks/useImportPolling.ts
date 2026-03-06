import { useEffect } from 'react'
import { importApi } from '@/lib/api'
import { POLL_INTERVAL_MS } from '@/lib/constants'
import { findGroupStatus } from '@/lib/mergeGroupStatus'
import type { EditableGroupState } from '@/types'
import type { DialogState } from './useImportState'

/** Map backend job status to the frontend dialog state.
 *  Backend status is authoritative — the frontend trusts it. */
export function backendStatusToDialogState(status: string): DialogState {
  switch (status) {
    case 'uploading':
      return 'upload'
    case 'staging':
      return 'preview'
    case 'active':
      return 'processing'
    default:
      // completed, failed, cancelled, expired
      return 'done'
  }
}

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
            const gs = findGroupStatus(g, status.groups)
            if (!gs) return g
            return {
              ...g,
              group_job_id: gs.group_job_id || g.group_job_id,
              status: gs.status as EditableGroupState['status'],
              processed: gs.processed_files,
              failed: gs.failed_files,
              total: gs.total_files || g.total,
              file_errors: gs.file_errors ?? g.file_errors,
            }
          }),
        )
        // Trust backend status for dialog state transitions
        const dialogState = backendStatusToDialogState(status.status)
        if (dialogState !== 'processing') {
          setState(dialogState)
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
