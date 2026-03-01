import { useState, useEffect, useMemo, useRef } from 'react'
import { EMPTY_FILTER } from '@/components/import/fileFilter'
import type { FileFilter } from '@/components/import/fileFilter'
import type { EditableFileState, EditableGroupState, TagData, ParsedTagVocab } from '@/types'

export const ALL_TAB = -1
export const ALL_GROUP_ID = '__all__'

export interface UseFileEditingOptions {
  /** Called with affected groups after any file mutation. Use for auto-save. */
  onGroupChange?: (affectedGroups: EditableGroupState[]) => void
}

export interface UseFileEditingReturn {
  // State
  groups: EditableGroupState[]
  setGroups: React.Dispatch<React.SetStateAction<EditableGroupState[]>>
  activeTab: number
  setActiveTab: React.Dispatch<React.SetStateAction<number>>
  selections: Record<string, Set<string>>
  setSelections: React.Dispatch<React.SetStateAction<Record<string, Set<string>>>>
  fileFilter: FileFilter
  setFileFilter: (filter: FileFilter) => void
  editingSvHeading: string | null
  setEditingSvHeading: (heading: string | null) => void
  tagVocab: ParsedTagVocab[]
  setTagVocab: React.Dispatch<React.SetStateAction<ParsedTagVocab[]>>
  authorSuggestions: string[]
  setAuthorSuggestions: React.Dispatch<React.SetStateAction<string[]>>

  // CRUD
  updateGroup: (index: number, updates: Partial<EditableGroupState>) => void
  updateFile: (
    groupIndex: number,
    relativePath: string,
    updates: Partial<EditableFileState>,
  ) => void
  updateFileAnyGroup: (relativePath: string, updates: Partial<EditableFileState>) => void
  updateFilesInGroup: (
    groupId: string,
    paths: string[],
    updates: Partial<EditableFileState>,
  ) => void

  // Selection
  toggleFileSelection: (groupId: string, relativePath: string) => void
  selectAllVisible: (groupId: string, visibleFiles: EditableFileState[]) => void
  deselectAll: (groupId: string) => void

  // Bulk ops
  bulkAddTag: (groupId: string | null, tag: TagData) => void
  bulkSetGrid: (groupId: string | null, gridded: boolean | null, gridType: string | null) => void
  bulkSetImageType: (groupId: string | null, value: 'battlemap' | 'scene') => void
  bulkSetSubgroup: (groupId: string | null, value: string) => void
  bulkExclude: (groupId: string | null) => void

  // Move ops
  moveFilesToGroup: (sourceGroupId: string, targetGroupId: string, paths: string[]) => void

  // Subgroup ops
  clearSubgroupLabel: (groupId: string, subgroup: string) => void
  renameSubgroup: (groupId: string, oldVal: string, newVal: string) => void

  // Derived values
  isAllTab: boolean
  activeGroup: EditableGroupState | null
  activeGroupId: string
  allSameAuthor: string
}

export function useFileEditing({
  onGroupChange,
}: UseFileEditingOptions = {}): UseFileEditingReturn {
  const [groups, setGroups] = useState<EditableGroupState[]>([])
  const [activeTab, setActiveTab] = useState(ALL_TAB)
  const [selections, setSelections] = useState<Record<string, Set<string>>>({})
  const [fileFilter, setFileFilter] = useState<FileFilter>(EMPTY_FILTER)
  const [editingSvHeading, setEditingSvHeading] = useState<string | null>(null)
  const [tagVocab, setTagVocab] = useState<ParsedTagVocab[]>([])
  const [authorSuggestions, setAuthorSuggestions] = useState<string[]>([])

  // Reset filter and editing state when switching tabs
  useEffect(() => {
    setFileFilter(EMPTY_FILTER)
    setEditingSvHeading(null)
  }, [activeTab])

  // ── Deferred onGroupChange callback ────────────────────────────
  // React 18 batches state updates, so updater fns inside setGroups()
  // may not execute synchronously. We accumulate affected groups in a
  // ref (keyed by ID to deduplicate) and flush via useEffect after render.
  const onGroupChangeRef = useRef(onGroupChange)
  onGroupChangeRef.current = onGroupChange
  const pendingGroupChanges = useRef<Map<string, EditableGroupState>>(new Map())

  useEffect(() => {
    const pending = pendingGroupChanges.current
    if (pending.size > 0) {
      const groups = [...pending.values()]
      pendingGroupChanges.current = new Map()
      onGroupChangeRef.current?.(groups)
    }
  })

  const notifyGroupChange = (groups: EditableGroupState[]) => {
    for (const g of groups) pendingGroupChanges.current.set(g.id, g)
  }

  // ── Helpers ──────────────────────────────────────────────────────

  /** Transforms files in a single group by ID, notifies onGroupChange. */
  const updateGroupFiles = (
    groupId: string,
    transform: (f: EditableFileState) => EditableFileState,
  ) => {
    setGroups((prev) => {
      const newGroups = prev.map((g) => {
        if (g.id !== groupId) return g
        return { ...g, files: g.files.map(transform) }
      })
      const affected = newGroups.find((g) => g.id === groupId)
      if (affected) notifyGroupChange([affected])
      return newGroups
    })
  }

  // ── CRUD ──────────────────────────────────────────────────────────

  const updateGroup = (index: number, updates: Partial<EditableGroupState>) => {
    setGroups((prev) => prev.map((g, i) => (i === index ? { ...g, ...updates } : g)))
  }

  const updateFile = (
    groupIndex: number,
    relativePath: string,
    updates: Partial<EditableFileState>,
  ) => {
    setGroups((prev) => {
      const currentGroup = prev[groupIndex]
      if (!currentGroup) return prev
      const newGroup = {
        ...currentGroup,
        files: currentGroup.files.map((f) =>
          f.relative_path === relativePath ? { ...f, ...updates } : f,
        ),
      }
      notifyGroupChange([newGroup])
      return prev.map((g, i) => (i === groupIndex ? newGroup : g))
    })
  }

  const updateFileAnyGroup = (relativePath: string, updates: Partial<EditableFileState>) => {
    setGroups((prev) => {
      const newGroups = prev.map((g) => ({
        ...g,
        files: g.files.map((f) => (f.relative_path === relativePath ? { ...f, ...updates } : f)),
      }))
      const affected = newGroups.filter((g) =>
        g.files.some((f) => f.relative_path === relativePath),
      )
      if (affected.length > 0) notifyGroupChange(affected)
      return newGroups
    })
  }

  const updateFilesInGroup = (
    groupId: string,
    paths: string[],
    updates: Partial<EditableFileState>,
  ) => {
    const pathSet = new Set(paths)
    updateGroupFiles(groupId, (f) => (pathSet.has(f.relative_path) ? { ...f, ...updates } : f))
  }

  // ── Move ops ────────────────────────────────────────────────────────

  const moveFilesToGroup = (sourceGroupId: string, targetGroupId: string, paths: string[]) => {
    const pathSet = new Set(paths)
    setGroups((prev) => {
      const sourceGroup = prev.find((g) => g.id === sourceGroupId)
      if (!sourceGroup) return prev

      const movedFiles = sourceGroup.files.filter((f) => pathSet.has(f.relative_path))
      if (movedFiles.length === 0) return prev

      const remainingFiles = sourceGroup.files.filter((f) => !pathSet.has(f.relative_path))
      const sourceEmpty = remainingFiles.length === 0

      let newGroups = prev.map((g) => {
        if (g.id === sourceGroupId) {
          return { ...g, files: remainingFiles, total: remainingFiles.length }
        }
        if (g.id === targetGroupId) {
          return {
            ...g,
            files: [...g.files, ...movedFiles],
            total: g.files.length + movedFiles.length,
          }
        }
        return g
      })

      if (sourceEmpty) {
        newGroups = newGroups.filter((g) => g.id !== sourceGroupId)
      }

      const affected = newGroups.filter((g) => g.id === sourceGroupId || g.id === targetGroupId)
      if (affected.length > 0) notifyGroupChange(affected)
      return newGroups
    })

    // Clear selections for source group
    setSelections((prev) => {
      const next = { ...prev }
      delete next[sourceGroupId]
      return next
    })
  }

  // ── Selection ─────────────────────────────────────────────────────

  const toggleFileSelection = (groupId: string, relativePath: string) => {
    setSelections((prev) => {
      const set = new Set(prev[groupId] ?? [])
      if (set.has(relativePath)) set.delete(relativePath)
      else set.add(relativePath)
      return { ...prev, [groupId]: set }
    })
  }

  const selectAllVisible = (groupId: string, visibleFiles: EditableFileState[]) => {
    setSelections((prev) => {
      const set = new Set<string>(prev[groupId] ?? [])
      visibleFiles
        .filter((f) => !f.excluded && !f.outOfScope)
        .forEach((f) => set.add(f.relative_path))
      return { ...prev, [groupId]: set }
    })
  }

  const deselectAll = (groupId: string) => {
    setSelections((prev) => ({ ...prev, [groupId]: new Set<string>() }))
  }

  // ── Bulk ops ──────────────────────────────────────────────────────

  // Generic helper: applies a transform to selected, non-excluded, non-outOfScope files.
  // Returns the updated groups array and saves affected groups via onGroupChange.
  const bulkUpdateFiles = (
    groupId: string | null,
    transform: (f: EditableFileState) => EditableFileState,
  ) => {
    const selId = groupId ?? ALL_GROUP_ID
    const sel = selections[selId] ?? new Set<string>()
    setGroups((prev) => {
      const newGroups = prev.map((g) => {
        if (groupId !== null && g.id !== groupId) return g
        return {
          ...g,
          files: g.files.map((f) => {
            if (!sel.has(f.relative_path) || f.excluded || f.outOfScope) return f
            return transform(f)
          }),
        }
      })
      const toSave = groupId !== null ? newGroups.filter((g) => g.id === groupId) : newGroups
      if (toSave.length > 0) notifyGroupChange(toSave)
      return newGroups
    })
  }

  const bulkAddTag = (groupId: string | null, tag: TagData) =>
    bulkUpdateFiles(groupId, (f) => {
      if (f.tags.some((t) => t.category === tag.category && t.value === tag.value)) return f
      return { ...f, tags: [...f.tags, tag] }
    })

  const bulkSetGrid = (groupId: string | null, gridded: boolean | null, gridType: string | null) =>
    bulkUpdateFiles(groupId, (f) => ({ ...f, gridded, grid_type: gridType }))

  const bulkSetImageType = (groupId: string | null, value: 'battlemap' | 'scene') =>
    bulkUpdateFiles(groupId, (f) => ({ ...f, image_type: value }))

  const bulkSetSubgroup = (groupId: string | null, value: string) =>
    bulkUpdateFiles(groupId, (f) => ({ ...f, subgroup: value.trim() || null }))

  const bulkExclude = (groupId: string | null) => {
    const selId = groupId ?? ALL_GROUP_ID
    const sel = selections[selId] ?? new Set<string>()
    setGroups((prev) => {
      const newGroups = prev.map((g) => {
        if (groupId !== null && g.id !== groupId) return g
        return {
          ...g,
          files: g.files.map((f) =>
            !sel.has(f.relative_path) || f.outOfScope ? f : { ...f, excluded: true },
          ),
        }
      })
      const toSave = groupId !== null ? newGroups.filter((g) => g.id === groupId) : newGroups
      if (toSave.length > 0) notifyGroupChange(toSave)
      return newGroups
    })
    deselectAll(selId)
  }

  // ── Subgroup ops ──────────────────────────────────────────────────

  const clearSubgroupLabel = (groupId: string, subgroup: string) =>
    updateGroupFiles(groupId, (f) =>
      f.subgroup === subgroup && !f.excluded && !f.outOfScope ? { ...f, subgroup: null } : f,
    )

  const renameSubgroup = (groupId: string, oldVal: string, newVal: string) =>
    updateGroupFiles(groupId, (f) =>
      f.subgroup === oldVal && !f.excluded && !f.outOfScope
        ? { ...f, subgroup: newVal.trim() || null }
        : f,
    )

  // ── Derived values ────────────────────────────────────────────────

  const isAllTab = activeTab === ALL_TAB
  const activeGroup = isAllTab ? null : (groups[activeTab] ?? null)
  const activeGroupId = isAllTab ? ALL_GROUP_ID : (activeGroup?.id ?? '')

  const allSameAuthor = useMemo(() => {
    if (groups.length === 0) return ''
    const first = groups[0].author
    return groups.every((g) => g.author === first) ? first : ''
  }, [groups])

  return {
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
    updateFilesInGroup,
    moveFilesToGroup,
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
  }
}
