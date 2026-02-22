import { useCallback, useEffect } from 'react'
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
  const saveNow = useCallback(() => {
    if (!jobId || groups.length === 0) return
    saveImportState(jobId, groups, activeTab, tagVocab)
  }, [jobId, groups, activeTab, tagVocab])

  // Auto-save every 60 seconds while in preview mode
  useEffect(() => {
    if (state !== 'preview' || !jobId) return
    const interval = setInterval(saveNow, AUTO_SAVE_INTERVAL_MS)
    return () => clearInterval(interval)
  }, [state, jobId, saveNow])

  // Save on beforeunload (browser close/navigate)
  useEffect(() => {
    if (!jobId || groups.length === 0) return
    const hasPending = groups.some((g) => g.status === 'pending' && !g.skip)
    if (!hasPending) return
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

    // Sync with backend for confirmed groups
    importApi
      .status(reconnectJobId)
      .then((status) => {
        setGroups((prev) =>
          prev.map((g) => {
            const gs = status.groups.find((s) => s.group_name === g.group_name)
            if (!gs) return g
            return {
              ...g,
              status: gs.status as EditableGroupState['status'],
              processed: gs.processed_files,
              failed: gs.failed_files,
              total: gs.total_files || g.total,
            }
          }),
        )
      })
      .catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps -- intentional: only reconnect on mount/jobId change; setters are stable dispatch functions
  }, [reconnectJobId])

  return { saveNow }
}
