/**
 * Hook that polls the background jobs API for status updates.
 *
 * Returns a list of background jobs (running + recently completed) and
 * a flag indicating whether any are currently active.  Polls every 10s
 * while active jobs exist.
 */

import { useEffect, useState, useCallback } from 'react'
import { jobApi } from '@/lib/api'
import { ACTIVE_POLL_INTERVAL_MS } from '@/lib/constants'
import type { BackgroundJob } from '@/types'

export interface UseBackgroundJobsReturn {
  jobs: BackgroundJob[]
  hasActive: boolean
  refresh: () => void
}

export function useBackgroundJobs(): UseBackgroundJobsReturn {
  const [jobs, setJobs] = useState<BackgroundJob[]>([])

  const refresh = useCallback(() => {
    jobApi
      .list()
      .then(setJobs)
      .catch(() => {
        // Backend unavailable — keep stale data
      })
  }, [])

  // Initial load
  useEffect(() => {
    refresh()
  }, [refresh])

  // Poll while any jobs are active
  useEffect(() => {
    const hasRunning = jobs.some((j) => j.status === 'queued' || j.status === 'running')
    if (!hasRunning) return
    const interval = setInterval(refresh, ACTIVE_POLL_INTERVAL_MS)
    return () => clearInterval(interval)
  }, [jobs, refresh])

  const hasActive = jobs.some((j) => j.status === 'queued' || j.status === 'running')

  return { jobs, hasActive, refresh }
}
