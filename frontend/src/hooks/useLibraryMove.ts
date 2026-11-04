/** Move library (desktop app; design/export-backup-move.md §10): the copy job, the
 * restart onto the new folders once it's copied, and the old folders left to delete. The
 * backend remembers a finished copy, so closing Settings meanwhile loses nothing. */

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
  const [restarting, setRestarting] = useState(false)
  // A backend that can't move (a server, or the developer's) answers 404: no Move…
  const status = useQuery({
    queryKey: MOVE_STATUS_KEY,
    queryFn: libraryApi.moveStatus,
    enabled: open,
    retry: false,
  })
  const refresh = () => void queryClient.invalidateQueries({ queryKey: MOVE_STATUS_KEY })
  const runningId = status.data?.job_id ?? null
  const { track, isComplete, isFailed } = job
  useEffect(() => {
    if (runningId) track(runningId)
  }, [runningId, track])
  useEffect(() => {
    if (isComplete || isFailed) refresh()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isComplete, isFailed])

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
      refresh()
    },
  })

  const copied = status.data?.copied ?? null
  const restart = async () => {
    if (!copied) return
    setRestarting(true)
    // Resolves only when it can't restart; otherwise the page reloads on the new folders
    const outcome = await window.electronAPI?.applyMove(copied)
    setRestarting(false)
    setError(outcome?.error ?? null)
  }
  const cancel = useMutation({ mutationFn: libraryApi.cancelMove, onSettled: refresh })

  return {
    job,
    start,
    error,
    available: !!status.data,
    movable: status.data?.movable ?? { app_data: false, store: false },
    copied,
    restart,
    restarting,
    cancel,
    movedFrom: status.data?.moved_from ?? null,
  }
}
