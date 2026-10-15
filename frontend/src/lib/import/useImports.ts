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
import type { ImportJobSummary } from './types'

export function useImportManagerSnapshot(
  manager: ImportManager = getImportManager(),
): ImportManagerSnapshot {
  return useSyncExternalStore(manager.subscribe, manager.getSnapshot)
}

export interface ImportJobView {
  job: ImportJobSummary | undefined
  upload: LocalUpload | undefined
}

/** One job's server summary plus this tab's upload progress for it. */
export function useImportJob(
  jobId: string | null,
  manager: ImportManager = getImportManager(),
): ImportJobView {
  const snapshot = useImportManagerSnapshot(manager)
  if (!jobId) return { job: undefined, upload: undefined }
  return {
    job: snapshot.jobs.find((j) => j.id === jobId),
    upload: snapshot.uploads[jobId],
  }
}

/** Start the app-wide poller while the component using it is mounted. */
export function useImportPollingLifecycle(manager: ImportManager = getImportManager()): void {
  useEffect(() => {
    manager.startPolling()
    return () => manager.stopPolling()
  }, [manager])
}
