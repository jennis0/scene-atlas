/**
 * Hook that provides the list of active imports for the Import Tray.
 *
 * Merges two data sources:
 * 1. localStorage index — has pending (unconfirmed) import jobs
 * 2. Backend /imports/active — has confirmed/running/recently-completed jobs
 *
 * Polls the backend every 10s while any jobs are active.
 */

import { useEffect, useState, useCallback, useRef } from 'react'
import { importApi } from '@/lib/api'
import { ACTIVE_POLL_INTERVAL_MS } from '@/lib/constants'
import {
  loadImportJobsIndex,
  cleanupExpiredImports,
  removeImportState,
  saveDismissedJob,
  loadDismissedJobs,
  pruneDismissedJobs,
} from '@/lib/importStorage'
import type { ImportJobSummary } from '@/types'
import type { ImportJobIndexEntry } from '@/lib/importStorage'

export interface ActiveImportJob {
  jobId: string
  label: string
  status:
    | 'uploading'
    | 'staging'
    | 'active'
    | 'awaiting_input'
    | 'running'
    | 'completed'
    | 'failed'
    | 'cancelled'
    | 'expired'
    | 'broken'
  totalGroups: number
  completedGroups: number
  failedGroups: number
  runningGroups: number
  pendingGroups: number
  totalFiles: number
  processedFiles: number
  createdAt: string
  /** Whether this job only exists in localStorage (not yet on backend). */
  localOnly: boolean
  /** Backend error message for failed/broken jobs. */
  errorMessage?: string
  /** Per-image file errors from processing. Populated by full status fetch (Task 9). */
  fileErrors?: Array<{ filename: string; reason: string; stage: string }>
}

export interface UseActiveImportsReturn {
  jobs: ActiveImportJob[]
  hasActive: boolean
  refresh: () => void
  dismissJob: (jobId: string) => void
  cancelJob: (jobId: string) => Promise<void>
  /** Fired once each time a job transitions to 'completed', with the completed job. */
  onJobCompleted: (cb: (job: ActiveImportJob) => void) => () => void
}

export function useActiveImports(): UseActiveImportsReturn {
  const [jobs, setJobs] = useState<ActiveImportJob[]>([])
  const prevJobStatusRef = useRef<Map<string, string>>(new Map())
  const completionListeners = useRef<Set<(job: ActiveImportJob) => void>>(new Set())
  /** Job IDs the user has dismissed — persisted to localStorage so they survive refresh. */
  const dismissedIdsRef = useRef<Set<string>>(loadDismissedJobs())
  /** Ref to access current jobs without adding it as a dependency to callbacks. */
  const jobsRef = useRef(jobs)
  jobsRef.current = jobs

  const refresh = useCallback(() => {
    cleanupExpiredImports()
    const localIndex = loadImportJobsIndex()
    const dismissed = dismissedIdsRef.current

    // Fetch backend active imports
    importApi
      .active()
      .then((response) => {
        const merged = mergeJobs(localIndex.jobs, response.jobs).filter(
          (j) => !dismissed.has(j.jobId),
        )
        setJobs(merged)
        // Prune dismissed IDs whose jobs are no longer tracked by the backend,
        // then sync the in-memory ref so it doesn't accumulate stale IDs.
        pruneDismissedJobs(new Set(response.jobs.map((j) => j.job_id)))
        dismissedIdsRef.current = loadDismissedJobs()
      })
      .catch(() => {
        // Backend unavailable — just use localStorage
        const localJobs = localIndex.jobs
          .map(localToActiveJob)
          .filter((j) => !dismissed.has(j.jobId))
        setJobs(localJobs)
      })
  }, [])

  // Initial load
  useEffect(() => {
    refresh()
  }, [refresh])

  // Poll every 10s while any jobs are active (running groups or active status)
  useEffect(() => {
    const hasRunning = jobs.some(
      (j) =>
        j.status === 'running' ||
        j.status === 'active' ||
        j.status === 'uploading' ||
        j.runningGroups > 0,
    )
    if (!hasRunning) return
    const interval = setInterval(refresh, ACTIVE_POLL_INTERVAL_MS)
    return () => clearInterval(interval)
  }, [jobs, refresh])

  // Detect transitions to 'completed' and fire listeners
  useEffect(() => {
    const prev = prevJobStatusRef.current
    const justCompleted: ActiveImportJob[] = []
    for (const job of jobs) {
      const prevStatus = prev.get(job.jobId)
      if (prevStatus && prevStatus !== 'completed' && job.status === 'completed') {
        justCompleted.push(job)
      }
      prev.set(job.jobId, job.status)
    }
    justCompleted.forEach((job) => {
      completionListeners.current.forEach((cb) => cb(job))
    })
  }, [jobs])

  const onJobCompleted = useCallback((cb: (job: ActiveImportJob) => void) => {
    completionListeners.current.add(cb)
    return () => completionListeners.current.delete(cb)
  }, [])

  const dismissJob = useCallback((jobId: string) => {
    dismissedIdsRef.current.add(jobId)
    saveDismissedJob(jobId)
    removeImportState(jobId)
    setJobs((prev) => prev.filter((j) => j.jobId !== jobId))
  }, [])

  const cancelJob = useCallback(async (jobId: string) => {
    const job = jobsRef.current.find((j) => j.jobId === jobId)
    if (!job?.localOnly) {
      try {
        await importApi.cancel(jobId)
      } catch {
        /* ignore errors */
      }
    }
    removeImportState(jobId)
    setJobs((prev) => prev.filter((j) => j.jobId !== jobId))
  }, [])

  const hasActive = jobs.some(
    (j) =>
      j.status === 'uploading' ||
      j.status === 'staging' ||
      j.status === 'active' ||
      j.status === 'awaiting_input' ||
      j.status === 'running' ||
      j.pendingGroups > 0,
  )

  return { jobs, hasActive, refresh, dismissJob, cancelJob, onJobCompleted }
}

function localToActiveJob(entry: ImportJobIndexEntry): ActiveImportJob {
  return {
    jobId: entry.jobId,
    label: entry.label,
    status: entry.hasRunningGroups ? 'running' : 'staging',
    totalGroups: entry.totalGroups,
    completedGroups: entry.completedGroups,
    failedGroups: entry.failedGroups,
    runningGroups: entry.hasRunningGroups ? 1 : 0,
    pendingGroups: entry.pendingGroups,
    totalFiles: 0,
    processedFiles: 0,
    createdAt: entry.createdAt,
    localOnly: true,
  }
}

function backendToActiveJob(summary: ImportJobSummary): ActiveImportJob {
  return {
    jobId: summary.job_id,
    label: summary.source_label ?? 'Import',
    status: summary.status as ActiveImportJob['status'],
    totalGroups: summary.total_groups,
    completedGroups: summary.completed_groups,
    failedGroups: summary.failed_groups,
    runningGroups: summary.running_groups,
    pendingGroups: summary.pending_groups, // Now from backend
    totalFiles: summary.total_files,
    processedFiles: summary.processed_files,
    createdAt: summary.created_at,
    localOnly: false,
    errorMessage: summary.error_message ?? undefined,
  }
}

function mergeJobs(
  localEntries: ImportJobIndexEntry[],
  backendSummaries: ImportJobSummary[],
): ActiveImportJob[] {
  const result = new Map<string, ActiveImportJob>()

  // Start with backend data (authoritative for confirmed jobs)
  for (const summary of backendSummaries) {
    result.set(summary.job_id, backendToActiveJob(summary))
  }

  // Merge in localStorage data (may have pending group counts)
  for (const entry of localEntries) {
    const existing = result.get(entry.jobId)
    if (existing) {
      // Backend now provides pending_groups, so it's authoritative.
      // Only supplement from localStorage if backend has 0 and job is non-terminal.
      const terminalStatuses = new Set(['completed', 'failed', 'cancelled', 'expired', 'broken'])
      if (
        existing.pendingGroups === 0 &&
        !terminalStatuses.has(existing.status) &&
        entry.pendingGroups > 0
      ) {
        existing.pendingGroups = entry.pendingGroups
      }
      existing.label = entry.label || existing.label
      // If localStorage has more groups (e.g. from analysis), update total
      if (entry.totalGroups > existing.totalGroups) {
        existing.totalGroups = entry.totalGroups
      }
    } else {
      // Only in localStorage (not yet confirmed to backend)
      result.set(entry.jobId, localToActiveJob(entry))
    }
  }

  // Sort by creation date, newest first
  return Array.from(result.values()).sort(
    (a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime(),
  )
}
