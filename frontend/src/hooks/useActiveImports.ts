/**
 * Hook that provides the list of active imports for the Import Tray.
 *
 * Merges two data sources:
 * 1. localStorage index — has pending (unconfirmed) import jobs
 * 2. Backend /imports/active — has confirmed/running/recently-completed jobs
 *
 * Polls the backend every 10s while any jobs are running.
 */

import { useEffect, useState, useCallback } from 'react'
import { importApi } from '@/lib/api'
import {
  loadImportJobsIndex,
  cleanupExpiredImports,
  removeImportState,
} from '@/lib/importStorage'
import type { ImportJobSummary } from '@/types'
import type { ImportJobIndexEntry } from '@/lib/importStorage'

export interface ActiveImportJob {
  jobId: string
  label: string
  status: 'staging' | 'running' | 'completed' | 'failed' | 'cancelled'
  totalGroups: number
  completedGroups: number
  failedGroups: number
  runningGroups: number
  pendingGroups: number
  totalFiles: number
  createdAt: string
  /** Whether this job only exists in localStorage (not yet on backend). */
  localOnly: boolean
}

export interface UseActiveImportsReturn {
  jobs: ActiveImportJob[]
  hasActive: boolean
  refresh: () => void
  dismissJob: (jobId: string) => void
}

export function useActiveImports(): UseActiveImportsReturn {
  const [jobs, setJobs] = useState<ActiveImportJob[]>([])

  const refresh = useCallback(() => {
    cleanupExpiredImports()
    const localIndex = loadImportJobsIndex()

    // Fetch backend active imports
    importApi.active().then((response) => {
      const merged = mergeJobs(localIndex.jobs, response.jobs)
      setJobs(merged)
    }).catch(() => {
      // Backend unavailable — just use localStorage
      const localJobs = localIndex.jobs.map(localToActiveJob)
      setJobs(localJobs)
    })
  }, [])

  // Initial load
  useEffect(() => {
    refresh()
  }, [refresh])

  // Poll every 10s while any jobs are running
  useEffect(() => {
    const hasRunning = jobs.some((j) => j.status === 'running' || j.runningGroups > 0)
    if (!hasRunning) return
    const interval = setInterval(refresh, 10_000)
    return () => clearInterval(interval)
  }, [jobs, refresh])

  const dismissJob = useCallback((jobId: string) => {
    removeImportState(jobId)
    setJobs((prev) => prev.filter((j) => j.jobId !== jobId))
  }, [])

  const hasActive = jobs.some((j) =>
    j.status === 'staging' || j.status === 'running' || j.pendingGroups > 0
  )

  return { jobs, hasActive, refresh, dismissJob }
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
    pendingGroups: 0, // Backend doesn't track unconfirmed groups
    totalFiles: summary.total_files,
    createdAt: summary.created_at,
    localOnly: false,
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
      // Backend has this job — merge in pending group count from localStorage
      existing.pendingGroups = entry.pendingGroups
      existing.label = entry.label || existing.label
      // If backend says staging but localStorage has groups, update total
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
    (a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime()
  )
}
