/** Move library (desktop app; design/export-backup-move.md §10): the copy job, the
 * restart onto the new folders once it's done, and the old folders left to delete. */

import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import type { LibraryFolderKind } from '@/electron'
import { libraryApi } from '@/lib/api/libraryApi'
import { getApiErrorMessage } from '@/lib/getErrorMessage'
import { useJobPolling } from '@/hooks/useJobPolling'

export const MOVE_STATUS_KEY = ['libraryMove'] as const

export type Movable = Extract<LibraryFolderKind, 'appData' | 'store'>

export function useLibraryMove(open: boolean) {
  const queryClient = useQueryClient()
  const job = useJobPolling()
  const [error, setError] = useState<string | null>(null)
  const status = useQuery({
    queryKey: MOVE_STATUS_KEY,
    queryFn: libraryApi.moveStatus,
    enabled: open,
  })
  const runningId = status.data?.job_id ?? null
  const { track, isComplete, result } = job
  useEffect(() => {
    if (runningId) track(runningId)
  }, [runningId, track])

  // Copied: restart on the new folders (the page reloads)
  useEffect(() => {
    if (!isComplete || !result) return
    void window.electronAPI
      ?.applyMove(result as { app_data?: string; store?: string })
      .then((outcome) => setError(outcome.error))
  }, [isComplete, result])

  const start = useMutation({
    mutationFn: async (kind: Movable) => {
      const chosen = await window.electronAPI?.chooseFolder(kind)
      if (!chosen) return null
      return libraryApi.startMove(kind === 'appData' ? { app_data: chosen } : { store: chosen })
    },
    onSuccess: (data) => {
      setError(null)
      if (data) job.track(data.job_id)
    },
    onError: (err) => {
      toast.error(getApiErrorMessage(err, 'Could not move the folder'))
      void queryClient.invalidateQueries({ queryKey: MOVE_STATUS_KEY })
    },
  })

  return { job, start, error, movedFrom: status.data?.moved_from ?? null }
}
