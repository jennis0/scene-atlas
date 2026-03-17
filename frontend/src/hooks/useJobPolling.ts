import { useEffect, useState, useCallback, useRef } from 'react'
import { jobApi } from '@/lib/api'
import { isNotFoundError } from '@/lib/getErrorMessage'
import type { BackgroundJob } from '@/types'

const DEFAULT_INTERVAL_MS = 2_000

interface UseJobPollingOptions {
  /** Polling interval in milliseconds (default 2000). */
  intervalMs?: number
}

interface UseJobPollingResult {
  /** Current job status, or null if no job is being tracked. */
  status: BackgroundJob['status'] | null
  /** Human-readable progress message from the job. */
  progress: string | null
  /** Integer percentage 0–100, or null if unavailable. */
  progressPct: number | null
  /** Error message if the job failed. */
  error: string | null
  /** True while the job is queued or running. */
  isRunning: boolean
  /** True when the job has completed successfully. */
  isComplete: boolean
  /** True when the job has failed. */
  isFailed: boolean
  /** Start tracking a new job ID. */
  track: (jobId: string) => void
  /** Stop tracking and reset state. */
  reset: () => void
}

/**
 * Shared hook for polling a background job's status.
 *
 * Usage:
 *   const job = useJobPolling()
 *   // After triggering a job:
 *   job.track(jobId)
 *   // In your UI:
 *   if (job.isRunning) { show spinner + job.progress }
 *   if (job.isComplete) { ... }
 */
export function useJobPolling(options?: UseJobPollingOptions): UseJobPollingResult {
  const intervalMs = options?.intervalMs ?? DEFAULT_INTERVAL_MS

  const [jobId, setJobId] = useState<string | null>(null)
  const [jobState, setJobState] = useState<BackgroundJob | null>(null)
  const jobIdRef = useRef<string | null>(null)

  const track = useCallback((id: string) => {
    jobIdRef.current = id
    setJobId(id)
    setJobState(null)
  }, [])

  const reset = useCallback(() => {
    jobIdRef.current = null
    setJobId(null)
    setJobState(null)
  }, [])

  useEffect(() => {
    if (!jobId) return

    let active = true

    const poll = async () => {
      try {
        const data = await jobApi.get(jobId)
        if (!active || jobIdRef.current !== jobId) return
        setJobState(data)
        // Stop polling when terminal
        if (data.status === 'completed' || data.status === 'failed') {
          return
        }
      } catch (err: unknown) {
        if (isNotFoundError(err)) {
          reset()
          return
        }
        // Transient error — continue polling
      }
      if (active) {
        timer = window.setTimeout(poll, intervalMs)
      }
    }

    let timer = window.setTimeout(poll, 0)
    return () => {
      active = false
      clearTimeout(timer)
    }
  }, [jobId, intervalMs, reset])

  const status = jobState?.status ?? null
  const isRunning = status === 'queued' || status === 'running'
  const isComplete = status === 'completed'
  const isFailed = status === 'failed'

  return {
    status,
    progress: jobState?.progress ?? null,
    progressPct: jobState?.progress_pct ?? null,
    error: jobState?.error ?? null,
    isRunning,
    isComplete,
    isFailed,
    track,
    reset,
  }
}
