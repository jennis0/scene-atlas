import { useQuery, useQueryClient } from '@tanstack/react-query'
import { jobApi } from '@/lib/api'
import { ACTIVE_POLL_INTERVAL_MS, IDLE_POLL_INTERVAL_MS } from '@/lib/constants'
import { QUERY_KEYS } from '@/lib/queryKeys'
import type { BackgroundJob } from '@/types'

export interface UseBackgroundJobsReturn {
  jobs: BackgroundJob[]
  hasActive: boolean
  refresh: () => void
  /** Remove a finished job from the list */
  dismiss: (jobId: string) => Promise<void>
  /** Remove every finished job from the list */
  dismissFinished: () => Promise<void>
}

const isActive = (j: BackgroundJob) => j.status === 'queued' || j.status === 'running'

/**
 * Background jobs (running and recently finished), excluding imports, which the
 * ImportManager tracks. Polls quickly while a job is active and slowly otherwise, so
 * jobs started elsewhere (tag management, library settings) still show up.
 */
export function useBackgroundJobs(): UseBackgroundJobsReturn {
  const queryClient = useQueryClient()
  const { data: jobs = [], refetch } = useQuery({
    queryKey: QUERY_KEYS.backgroundJobs,
    queryFn: async () => (await jobApi.list()).filter((j) => !j.name.startsWith('Import')),
    refetchInterval: (query) =>
      query.state.data?.some(isActive) ? ACTIVE_POLL_INTERVAL_MS : IDLE_POLL_INTERVAL_MS,
    retry: false,
  })

  // Drop the rows straight away rather than waiting for the next (slow, when idle) poll
  const forget = (keep: (j: BackgroundJob) => boolean) =>
    queryClient.setQueryData<BackgroundJob[]>(QUERY_KEYS.backgroundJobs, (old) => old?.filter(keep))

  return {
    jobs,
    hasActive: jobs.some(isActive),
    refresh: () => void refetch(),
    dismiss: async (jobId) => {
      await jobApi.dismiss(jobId)
      forget((j) => j.id !== jobId)
    },
    dismissFinished: async () => {
      await jobApi.dismissFinished()
      forget(isActive)
    },
  }
}
