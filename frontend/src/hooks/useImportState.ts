import { useState, useRef, useCallback, useEffect, useMemo } from 'react'
import { tagApi, imageApi, importApi } from '@/lib/api'
import { parseTagVocabulary } from '@/components/import/types'
import { EMPTY_FILTER, applyFileFilter } from '@/components/import/fileFilter'
import type { FileFilter } from '@/components/import/fileFilter'
import type {
  EditableFileState,
  EditableGroupState,
  TagData,
  ImportConfirmFile,
  ParsedTagVocab,
} from '@/types'
import { removeImportState } from '@/lib/importStorage'
import { useFileEditing, ALL_TAB, ALL_GROUP_ID } from './useFileEditing'
import { useImportUpload } from './useImportUpload'
import { useImportPolling } from './useImportPolling'
import { useImportPersistence } from './useImportPersistence'

// Re-export constants so existing importers (ImportGroupNav, etc.) keep working
export { ALL_TAB, ALL_GROUP_ID }

export type DialogState = 'upload' | 'preview' | 'processing' | 'done'

export interface UseImportStateReturn {
  // Core state
  state: DialogState
  uploading: boolean
  uploadError: string | null
  uploadPhase: string | null
  skippedFiles: string[]
  jobId: string | null
  groups: EditableGroupState[]
  activeTab: number
  tagVocab: ParsedTagVocab[]
  selections: Record<string, Set<string>>
  fileFilter: FileFilter
  authorSuggestions: string[]
  editingSvHeading: string | null
  defaultImageType: 'battlemap' | 'scene'

  // Refs
  fileInputRef: React.RefObject<HTMLInputElement>
  folderInputRef: React.RefObject<HTMLInputElement>

  // Derived values
  isAllTab: boolean
  activeGroup: EditableGroupState | null
  activeGroupId: string
  allPendingFiles: EditableFileState[]
  sourceFiles: EditableFileState[]
  filteredFiles: EditableFileState[]
  activeSelection: Set<string>
  groupSubgroups: string[]
  distinctSubgroups: (string | null)[]
  showSubgroupHeadings: boolean
  subgroupGroups: { subgroup: string | null; files: EditableFileState[] }[]
  pendingGroups: EditableGroupState[]
  completedCount: number
  totalFiles: number
  allSameAuthor: string
  duplicateCount: number
  skippedDuplicateCount: number
  canImportActive: boolean
  canImportAll: boolean
  canMergeAll: boolean

  // State setters
  setState: (state: DialogState) => void
  setActiveTab: (tab: number) => void
  setFileFilter: (filter: FileFilter) => void
  setEditingSvHeading: (heading: string | null) => void
  setGroups: React.Dispatch<React.SetStateAction<EditableGroupState[]>>
  setDefaultImageType: (type: 'battlemap' | 'scene') => void

  // Actions
  reset: () => void
  handleFileSelect: (e: React.ChangeEvent<HTMLInputElement>) => Promise<void>
  handleDrop: (e: React.DragEvent) => Promise<void>
  updateGroup: (index: number, updates: Partial<EditableGroupState>) => void
  updateFile: (
    groupIndex: number,
    relativePath: string,
    updates: Partial<EditableFileState>,
  ) => void
  updateFileAnyGroup: (relativePath: string, updates: Partial<EditableFileState>) => void
  mergeGroups: (sourceIndex: number, targetIndex: number) => void
  mergeAllGroups: () => void
  toggleFileSelection: (groupId: string, relativePath: string) => void
  selectAllVisible: (groupId: string, visibleFiles: EditableFileState[]) => void
  deselectAll: (groupId: string) => void
  bulkAddTag: (groupId: string | null, tag: TagData) => void
  bulkSetGrid: (groupId: string | null, gridded: boolean | null, gridType: string | null) => void
  bulkSetImageType: (groupId: string | null, value: 'battlemap' | 'scene') => void
  bulkSetSubgroup: (groupId: string | null, value: string) => void
  bulkExclude: (groupId: string | null) => void
  bulkSetDuplicateAction: (groupId: string | null, action: 'skip' | 'import') => void
  clearSubgroupLabel: (groupId: string, subgroup: string) => void
  renameSubgroup: (groupId: string, oldVal: string, newVal: string) => void
  moveToNewGroup: (sourceGroupId: string) => void
  handleConfirmGroup: (index: number) => Promise<void>
  handleConfirmAll: () => Promise<void>
  handleFinalize: () => Promise<void>
  buildConfirmFiles: (group: EditableGroupState) => ImportConfirmFile[]
  saveNow: () => void
}

export function useImportState(
  onActiveChange?: (active: boolean) => void,
  reconnectJobId?: string,
): UseImportStateReturn {
  const [state, setState] = useState<DialogState>('upload')
  const [jobId, setJobId] = useState<string | null>(null)
  // Tracks whether tag vocab and author suggestions have been fetched for this session
  const hasFetchedPreviewData = useRef(false)

  // ── Shared file-editing state and mutations ────────────────────────
  const {
    groups,
    setGroups,
    activeTab,
    setActiveTab,
    selections,
    setSelections,
    fileFilter,
    setFileFilter,
    editingSvHeading,
    setEditingSvHeading,
    tagVocab,
    setTagVocab,
    authorSuggestions,
    setAuthorSuggestions,
    updateGroup,
    updateFile,
    updateFileAnyGroup,
    toggleFileSelection,
    selectAllVisible,
    deselectAll,
    bulkAddTag,
    bulkSetGrid,
    bulkSetImageType,
    bulkSetSubgroup,
    bulkExclude,
    clearSubgroupLabel,
    renameSubgroup,
    isAllTab,
    activeGroup,
    activeGroupId,
    allSameAuthor,
  } = useFileEditing()

  // ── Upload pipeline ─────────────────────────────────────────────
  const {
    fileInputRef,
    folderInputRef,
    blobUrlsRef,
    uploading,
    uploadError,
    uploadPhase,
    skippedFiles,
    defaultImageType,
    setDefaultImageType,
    handleFileSelect,
    handleDrop,
  } = useImportUpload({ setGroups, setJobId: (id) => setJobId(id), setState, setActiveTab })

  // ── Polling ─────────────────────────────────────────────────────
  useImportPolling({ state, jobId, setGroups, setState })

  // ── Persistence ─────────────────────────────────────────────────
  const { saveNow } = useImportPersistence({
    jobId,
    groups,
    state,
    activeTab,
    tagVocab,
    reconnectJobId,
    setGroups,
    setActiveTab,
    setTagVocab,
    setJobId: (id) => setJobId(id),
    setState,
  })

  // Use a ref so the effect only re-runs when `state` changes, not when the
  // callback prop identity changes (inline arrow functions in Gallery would
  // otherwise create an infinite render loop via setJobs → re-render → new fn).
  const onActiveChangeRef = useRef(onActiveChange)
  onActiveChangeRef.current = onActiveChange
  useEffect(() => {
    onActiveChangeRef.current?.(state === 'processing')
  }, [state])

  // Fetch tag vocab + author suggestions once when entering preview
  useEffect(() => {
    if (state !== 'preview') return
    if (hasFetchedPreviewData.current) return
    hasFetchedPreviewData.current = true
    tagApi
      .getCategories()
      .then((cats) => setTagVocab(parseTagVocabulary(cats)))
      .catch(() => {
        /* non-fatal: tag picker will be empty but import can still proceed */
      })
    imageApi
      .getAuthors()
      .then(setAuthorSuggestions)
      .catch(() => {
        /* non-fatal: author suggestions will be empty */
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps -- intentional: fetch-once guard via ref; setters are stable
  }, [state])

  const reset = useCallback(() => {
    blobUrlsRef.current.forEach((url) => URL.revokeObjectURL(url))
    blobUrlsRef.current = []
    setState('upload')
    setJobId(null)
    setGroups([])
    setActiveTab(ALL_TAB)
    setTagVocab([])
    setSelections({})
    setFileFilter(EMPTY_FILTER)
    setEditingSvHeading(null)
    setAuthorSuggestions([])
  }, [
    blobUrlsRef,
    setGroups,
    setActiveTab,
    setTagVocab,
    setSelections,
    setFileFilter,
    setEditingSvHeading,
    setAuthorSuggestions,
  ])

  // ── Import-specific mutations ─────────────────────────────────────

  const mergeGroups = (sourceIndex: number, targetIndex: number) => {
    setGroups((prev) => {
      const source = prev[sourceIndex]
      const target = prev[targetIndex]
      if (!source || !target) return prev
      return prev
        .map((g, i) => {
          if (i === targetIndex)
            return {
              ...g,
              files: [...g.files, ...source.files],
              total: g.files.length + source.files.length,
            }
          return g
        })
        .filter((_, i) => i !== sourceIndex)
    })
    setActiveTab((prev) => {
      if (prev === ALL_TAB) return groups.length <= 2 ? 0 : ALL_TAB
      if (sourceIndex < prev) return prev - 1
      if (sourceIndex === prev) return Math.min(targetIndex, groups.length - 2)
      return prev
    })
  }

  const mergeAllGroups = () => {
    const eligible = groups
      .map((g, i) => ({ g, i }))
      .filter(({ g }) => g.status === 'pending' && !g.skip)
    if (eligible.length < 2) return

    const targetIdx = eligible[0].i
    const sourceIndices = new Set(eligible.slice(1).map(({ i }) => i))
    const sourceFiles = eligible.slice(1).flatMap(({ g }) => g.files)

    setGroups((prev) =>
      prev
        .map((g, i) => {
          if (i === targetIdx) {
            const merged = [...g.files, ...sourceFiles]
            return { ...g, files: merged, total: merged.length }
          }
          return g
        })
        .filter((_, i) => !sourceIndices.has(i)),
    )

    // All sourceIndices are > targetIdx (targetIdx is the minimum eligible index),
    // so no elements before targetIdx are removed — the merged group stays at targetIdx.
    setActiveTab(targetIdx)
  }

  const bulkSetDuplicateAction = (groupId: string | null, action: 'skip' | 'import') => {
    setGroups((prev) =>
      prev.map((g) => {
        if (groupId !== null && g.id !== groupId) return g
        return {
          ...g,
          files: g.files.map((f) => (f.duplicate_of ? { ...f, duplicate_action: action } : f)),
        }
      }),
    )
  }

  const moveToNewGroup = (sourceGroupId: string) => {
    const sourceIndex = groups.findIndex((g) => g.id === sourceGroupId)
    if (sourceIndex === -1) return
    const source = groups[sourceIndex]
    const sel = selections[sourceGroupId] ?? new Set<string>()
    if (sel.size === 0) return

    const movedFiles = source.files.filter((f) => sel.has(f.relative_path))
    const remainingFiles = source.files.filter((f) => !sel.has(f.relative_path))

    const newGroup: EditableGroupState = {
      id: crypto.randomUUID(),
      author: source.author,
      group_name: `${source.group_name} (split)`,
      files: movedFiles,
      skip: false,
      status: 'pending',
      processed: 0,
      failed: 0,
      total: movedFiles.length,
    }

    const newGroups = [
      ...groups.map((g, i) =>
        i === sourceIndex ? { ...g, files: remainingFiles, total: remainingFiles.length } : g,
      ),
      newGroup,
    ]
    setGroups(newGroups)
    setSelections((prev) => {
      const next = { ...prev }
      delete next[sourceGroupId]
      return next
    })
    setActiveTab(newGroups.length - 1)
  }

  // ── Confirm ───────────────────────────────────────────────────────

  const buildConfirmFiles = (group: EditableGroupState): ImportConfirmFile[] =>
    group.files
      .filter((f) => !f.excluded && f.duplicate_action !== 'skip')
      .map((f) => {
        const base: ImportConfirmFile = {
          relative_path: f.relative_path,
          name: f.name,
          media_type: f.media_type,
          tags: f.tags,
          gridded: f.gridded,
          grid_width: f.grid_width,
          grid_height: f.grid_height,
          grid_type: f.grid_type ?? null,
          subgroup: f.subgroup,
          image_type: f.image_type,
        }
        if (f.content_hash) base.content_hash = f.content_hash
        if (f.duplicate_of && f.duplicate_action === 'import') {
          base.reuse_storage_key = f.duplicate_of.storage_key
          base.reuse_thumbnail_key = f.duplicate_of.thumbnail_key ?? undefined
        }
        return base
      })

  const handleConfirmGroup = async (index: number) => {
    if (!jobId) return
    const group = groups[index]
    if (group.skip) return
    const confirmFiles = buildConfirmFiles(group)
    if (confirmFiles.length === 0) return
    updateGroup(index, { status: 'running' })
    setState('processing')
    try {
      // Tell backend which groups remain unconfirmed
      const remaining = groups
        .filter((g, i) => i !== index && g.status === 'pending' && !g.skip)
        .map((g) => g.group_name)
      const response = await importApi.confirm(jobId, {
        author: group.author,
        group_name: group.group_name,
        files: confirmFiles,
        remaining_groups: remaining,
      })
      // Store group_job_id from response for robust status matching
      const matchedGroup = response.groups.find((gs) => gs.group_name === group.group_name)
      if (matchedGroup?.group_job_id) {
        updateGroup(index, { group_job_id: matchedGroup.group_job_id })
      }
      setTimeout(saveNow, 100)
    } catch {
      updateGroup(index, { status: 'failed' })
    }
  }

  const handleConfirmAll = async () => {
    if (!jobId) return
    setState('processing')
    const toSubmit: {
      i: number
      author: string
      group_name: string
      files: ImportConfirmFile[]
    }[] = []
    groups.forEach((group, i) => {
      if (group.status !== 'pending' || group.skip) return
      const confirmFiles = buildConfirmFiles(group)
      if (confirmFiles.length === 0) {
        updateGroup(i, { status: 'completed', processed: 0 })
        return
      }
      toSubmit.push({ i, author: group.author, group_name: group.group_name, files: confirmFiles })
    })
    if (toSubmit.length === 0) return
    toSubmit.forEach(({ i }) => updateGroup(i, { status: 'running' }))
    try {
      const response = await importApi.confirmAll(
        jobId,
        toSubmit.map(({ author, group_name, files }) => ({ author, group_name, files })),
      )
      // Store group_job_ids from response for robust status matching
      for (const { i, group_name } of toSubmit) {
        const matchedGroup = response.groups.find((gs) => gs.group_name === group_name)
        if (matchedGroup?.group_job_id) {
          updateGroup(i, { group_job_id: matchedGroup.group_job_id })
        }
      }
      setTimeout(saveNow, 100)
    } catch {
      toSubmit.forEach(({ i }) => updateGroup(i, { status: 'failed' }))
    }
  }

  const handleFinalize = async () => {
    if (!jobId) return
    try {
      await importApi.finalize(jobId)
      removeImportState(jobId)
      setState('done')
    } catch (err) {
      console.error('Finalize failed:', err)
    }
  }

  // ── Derived values ────────────────────────────────────────────────

  const allPendingFiles = useMemo(
    () => groups.filter((g) => g.status === 'pending' && !g.skip).flatMap((g) => g.files),
    [groups],
  )
  const sourceFiles = useMemo(
    () => (isAllTab ? allPendingFiles : (activeGroup?.files ?? [])),
    [isAllTab, allPendingFiles, activeGroup],
  )
  const filteredFiles = useMemo(
    () => applyFileFilter(sourceFiles, fileFilter),
    [sourceFiles, fileFilter],
  )
  const activeSelection = selections[activeGroupId] ?? new Set<string>()

  const groupSubgroups = useMemo(
    () =>
      [
        ...new Set(
          sourceFiles.filter((f) => !f.excluded && f.subgroup).map((f) => f.subgroup as string),
        ),
      ].sort(),
    [sourceFiles],
  )

  const distinctSubgroups = useMemo(
    () =>
      [...new Set(filteredFiles.map((f) => f.subgroup))].sort((a, b) => {
        if (a === null) return -1
        if (b === null) return 1
        return (a ?? '').localeCompare(b ?? '')
      }),
    [filteredFiles],
  )

  const showSubgroupHeadings = distinctSubgroups.length > 1
  const subgroupGroups = distinctSubgroups.map((sv) => ({
    subgroup: sv,
    files: filteredFiles.filter((f) => f.subgroup === sv),
  }))

  const pendingGroups = groups.filter((g) => g.status === 'pending' && !g.skip)
  const completedCount = groups.filter((g) => g.status === 'completed').length
  const totalFiles = groups.reduce((sum, g) => sum + g.files.length, 0)
  const duplicateCount = useMemo(
    () => sourceFiles.filter((f) => !f.excluded && f.duplicate_of).length,
    [sourceFiles],
  )
  const skippedDuplicateCount = useMemo(
    () => sourceFiles.filter((f) => !f.excluded && f.duplicate_action === 'skip').length,
    [sourceFiles],
  )

  const canImportActive =
    !isAllTab &&
    activeGroup?.status === 'pending' &&
    !!activeGroup.author &&
    !activeGroup.files.every((f) => f.excluded)
  const canImportAll = pendingGroups.length > 0 && pendingGroups.every((g) => !!g.author)
  const canMergeAll = pendingGroups.length >= 2

  return {
    state,
    uploading,
    uploadError,
    uploadPhase,
    skippedFiles,
    jobId,
    groups,
    activeTab,
    tagVocab,
    selections,
    fileFilter,
    authorSuggestions,
    editingSvHeading,
    defaultImageType,
    fileInputRef,
    folderInputRef,
    isAllTab,
    activeGroup,
    activeGroupId,
    allPendingFiles,
    sourceFiles,
    filteredFiles,
    activeSelection,
    groupSubgroups,
    distinctSubgroups,
    showSubgroupHeadings,
    subgroupGroups,
    pendingGroups,
    completedCount,
    totalFiles,
    duplicateCount,
    skippedDuplicateCount,
    allSameAuthor,
    canImportActive,
    canImportAll,
    canMergeAll,
    setState,
    setActiveTab,
    setFileFilter,
    setEditingSvHeading,
    setGroups,
    setDefaultImageType,
    reset,
    handleFileSelect,
    handleDrop,
    updateGroup,
    updateFile,
    updateFileAnyGroup,
    mergeGroups,
    mergeAllGroups,
    toggleFileSelection,
    selectAllVisible,
    deselectAll,
    bulkAddTag,
    bulkSetGrid,
    bulkSetImageType,
    bulkSetSubgroup,
    bulkExclude,
    bulkSetDuplicateAction,
    clearSubgroupLabel,
    renameSubgroup,
    moveToNewGroup,
    handleConfirmGroup,
    handleConfirmAll,
    handleFinalize,
    buildConfirmFiles,
    saveNow,
  }
}
