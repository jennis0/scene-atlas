import { useCallback, useEffect, useRef } from 'react'
import { AUTO_SAVE_INTERVAL_MS } from '@/lib/constants'
import {
  saveImportState,
  loadImportState,
  restorePreviewUrls,
  removeImportState,
} from '@/lib/importStorage'
import { importApi } from '@/lib/api'
import { mapAnalysisToEditable } from './useImportUpload'
import { backendStatusToDialogState } from './useImportPolling'
import { ALL_TAB } from './useFileEditing'
import type { EditableGroupState, ParsedTagVocab } from '@/types'
import type { DialogState } from './useImportState'

interface UseImportPersistenceOptions {
  jobId: string | null
  groups: EditableGroupState[]
  state: DialogState
  activeTab: number
  tagVocab: ParsedTagVocab[]
  reconnectJobId: string | undefined
  setGroups: React.Dispatch<React.SetStateAction<EditableGroupState[]>>
  setActiveTab: React.Dispatch<React.SetStateAction<number>>
  setTagVocab: React.Dispatch<React.SetStateAction<ParsedTagVocab[]>>
  setJobId: (id: string) => void
  setState: (state: DialogState) => void
}

export interface UseImportPersistenceReturn {
  saveNow: () => void
}

export function useImportPersistence({
  jobId,
  groups,
  state,
  activeTab,
  tagVocab,
  reconnectJobId,
  setGroups,
  setActiveTab,
  setTagVocab,
  setJobId,
  setState,
}: UseImportPersistenceOptions): UseImportPersistenceReturn {
  // Inner save captures the latest state from each render.
  const saveNowInner = useCallback(() => {
    if (!jobId || groups.length === 0) return
    saveImportState(jobId, groups, activeTab, tagVocab)
  }, [jobId, groups, activeTab, tagVocab])

  // Ref keeps the latest version so callers in async closures / setTimeout
  // always persist current state rather than a stale snapshot.
  const saveNowRef = useRef(saveNowInner)
  useEffect(() => {
    saveNowRef.current = saveNowInner
  }, [saveNowInner])

  const saveNow = useCallback(() => {
    saveNowRef.current()
  }, [])

  // Auto-save periodically while in preview or processing mode.
  // During processing, this keeps localStorage in sync with group status
  // updates from useImportPolling so the import tray has accurate data.
  useEffect(() => {
    if ((state !== 'preview' && state !== 'processing') || !jobId) return
    const interval = setInterval(saveNow, AUTO_SAVE_INTERVAL_MS)
    return () => clearInterval(interval)
  }, [state, jobId, saveNow])

  // Save on beforeunload (browser close/navigate)
  useEffect(() => {
    if (!jobId || groups.length === 0) return
    const hasActive = groups.some(
      (g) => (g.status === 'pending' && !g.skip) || g.status === 'running',
    )
    if (!hasActive) return
    const handler = () => saveNow()
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [jobId, groups, saveNow])

  // Reconnect to an existing job on mount (e.g. dialog reopened after page reload)
  useEffect(() => {
    if (!reconnectJobId) return
    const persisted = loadImportState(reconnectJobId)
    if (!persisted) return

    setJobId(reconnectJobId)

    // If localStorage has no groups, the dialog was closed during upload.
    // Check backend status and fetch analysis if available.
    if (persisted.groups.length === 0) {
      importApi
        .status(reconnectJobId)
        .then((status) => {
          const dialogState = backendStatusToDialogState(status.status)
          if (dialogState === 'upload') {
            setState('upload')
          } else if (dialogState === 'preview' || dialogState === 'processing') {
            // Upload finished — fetch full analysis to rebuild groups
            importApi
              .getAnalysis(reconnectJobId)
              .then((analysis) => {
                const groups = mapAnalysisToEditable(analysis, reconnectJobId)
                setGroups(groups)
                setActiveTab(groups.length > 1 ? ALL_TAB : 0)
                setState('preview')
              })
              .catch(() => {
                setState('done')
              })
          } else {
            setState('done')
          }
        })
        .catch(() => {
          removeImportState(reconnectJobId)
        })
      return
    }

    // Normal reconnect path: localStorage has groups
    const restoredGroups = restorePreviewUrls(reconnectJobId, persisted.groups)
    setGroups(restoredGroups)
    setActiveTab(persisted.activeTab)
    if (persisted.tagVocab.length > 0) setTagVocab(persisted.tagVocab)

    // Set an initial state from localStorage for immediate display,
    // then sync with backend below for the authoritative state.
    const hasRunning = restoredGroups.some((g) => g.status === 'running')
    const hasPending = restoredGroups.some((g) => g.status === 'pending' && !g.skip)
    if (hasRunning) {
      setState('processing')
    } else if (hasPending) {
      setState('preview')
    } else {
      setState('done')
    }

    // Sync with backend — backend status is authoritative
    importApi
      .status(reconnectJobId)
      .then((status) => {
        setGroups((prev) => {
          return prev.map((g) => {
            // Match by group_job_id (robust) or fall back to group_name
            const gs =
              (g.group_job_id && status.groups.find((s) => s.group_job_id === g.group_job_id)) ||
              status.groups.find((s) => s.group_name === g.group_name)
            if (!gs) return g
            return {
              ...g,
              group_job_id: gs.group_job_id || g.group_job_id,
              status: gs.status as EditableGroupState['status'],
              processed: gs.processed_files,
              failed: gs.failed_files,
              total: gs.total_files || g.total,
            }
          })
        })
        // Trust backend status for dialog state
        setState(backendStatusToDialogState(status.status))
      })
      .catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps -- intentional: only reconnect on mount/jobId change; setters are stable dispatch functions
  }, [reconnectJobId])

  return { saveNow }
}
