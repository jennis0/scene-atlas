/**
 * React bindings for ImportManager. Components read import state only through
 * these hooks; they never fetch or poll themselves.
 */

import { useEffect, useSyncExternalStore } from 'react'
import {
  getImportManager,
  type ImportManager,
  type ImportManagerSnapshot,
  type LocalUpload,
} from './ImportManager'
import type { ImportJobDetail, ImportJobSummary } from './types'
import type { DetailScope } from './importClient'

export function useImportManagerSnapshot(
  manager: ImportManager = getImportManager(),
): ImportManagerSnapshot {
  return useSyncExternalStore(manager.subscribe, manager.getSnapshot)
}

export interface ImportJobView {
  job: ImportJobSummary | undefined
  upload: LocalUpload | undefined
  /** Per-group detail; present while watched (``watch: true``). */
  detail: ImportJobDetail | undefined
}

/**
 * One job's server summary plus this tab's upload progress for it. With
 * ``watch``, also keeps its per-group detail fresh while mounted.
 */
interface ImportJobOptions {
  /** Keep the job's detail fresh while mounted */
  watch?: boolean
  /** Which groups the detail needs (the progress view needs only those importing now) */
  scope?: DetailScope
  manager?: ImportManager
}

export function useImportJob(
  jobId: string | null,
  { watch = false, scope = 'all', manager = getImportManager() }: ImportJobOptions = {},
): ImportJobView {
  const snapshot = useImportManagerSnapshot(manager)
  useEffect(() => {
    if (!watch || !jobId) return
    return manager.watchJob(jobId, scope)
  }, [watch, scope, jobId, manager])
  if (!jobId) return { job: undefined, upload: undefined, detail: undefined }
  return {
    job: snapshot.jobs.find((j) => j.id === jobId),
    upload: snapshot.uploads[jobId],
    detail: snapshot.details[jobId],
  }
}

/** Start the app-wide poller while the component using it is mounted. */
export function useImportPollingLifecycle(manager: ImportManager = getImportManager()): void {
  useEffect(() => {
    manager.startPolling()
    return () => manager.stopPolling()
  }, [manager])
}
