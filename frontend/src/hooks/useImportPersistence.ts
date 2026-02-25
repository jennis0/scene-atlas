import { useCallback, useEffect, useRef } from 'react'
import { AUTO_SAVE_INTERVAL_MS } from '@/lib/constants'
import { saveImportState, loadImportState, restorePreviewUrls } from '@/lib/importStorage'
import { importApi } from '@/lib/api'
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
    const restoredGroups = restorePreviewUrls(reconnectJobId, persisted.groups)
    setGroups(restoredGroups)
    setActiveTab(persisted.activeTab)
    if (persisted.tagVocab.length > 0) setTagVocab(persisted.tagVocab)

    // Determine dialog state based on group statuses
    const hasRunning = restoredGroups.some((g) => g.status === 'running')
    const hasPending = restoredGroups.some((g) => g.status === 'pending' && !g.skip)
    if (hasRunning) {
      setState('processing')
    } else if (hasPending) {
      setState('preview')
    } else {
      setState('done')
    }

    // Sync with backend for confirmed groups and re-derive dialog state
    importApi
      .status(reconnectJobId)
      .then((status) => {
        setGroups((prev) => {
          const next = prev.map((g) => {
            const gs = status.groups.find((s) => s.group_name === g.group_name)
            if (!gs) return g
            return {
              ...g,
              status: gs.status as EditableGroupState['status'],
              processed: gs.processed_files,
              failed: gs.failed_files,
              total: gs.total_files || g.total,
            }
          })
          // Re-derive dialog state after backend sync
          const hasRunningNow = next.some((g) => g.status === 'running')
          const hasPendingNow = next.some((g) => g.status === 'pending' && !g.skip)
          const backendPending = (status.pending_group_count ?? 0) > 0
          if (hasRunningNow) {
            setState('processing')
          } else if (hasPendingNow || backendPending) {
            setState('preview')
          } else {
            setState('done')
          }
          return next
        })
      })
      .catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps -- intentional: only reconnect on mount/jobId change; setters are stable dispatch functions
  }, [reconnectJobId])

  return { saveNow }
}
