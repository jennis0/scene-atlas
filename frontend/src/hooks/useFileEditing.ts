import { useState, useEffect, useRef } from 'react'
import { EMPTY_FILTER } from '@/components/import/fileFilter'
import type { FileFilter } from '@/components/import/fileFilter'
import type { EditableFileState, EditableGroupState, ParsedTagVocab } from '@/types'

export const ALL_TAB = -1
export const ALL_GROUP_ID = '__all__'
export const MULTI_GROUP_ID = '__multi__'

/** A bulk edit's target: one group, the multi-selected groups, or null for every group. */
export type BulkScope = string | string[] | null

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
  updateGroup: (groupId: string, updates: Partial<EditableGroupState>) => void
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

  // Bulk ops, applied to the selected files in scope
  /** The selected, in-scope, not excluded files a bulk action applies to */
  selectedInScope: (scope: BulkScope) => EditableFileState[]
  /** Change files (by relative_path) in whichever groups hold them, without saving
   *  the groups: for edits already saved some other way (bulk image edits) */
  patchFiles: (paths: Set<string>, transform: (f: EditableFileState) => EditableFileState) => void
  bulkExclude: (scope: BulkScope) => void

  // Subgroup ops
  clearSubgroupLabel: (groupId: string, subgroup: string) => void
  renameSubgroup: (groupId: string, oldVal: string, newVal: string) => void

  // Derived values
  isAllTab: boolean
  activeGroup: EditableGroupState | null
  activeGroupId: string
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

  // Deferred onGroupChange callback
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

  // Helpers

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

  // CRUD

  const updateGroup = (groupId: string, updates: Partial<EditableGroupState>) => {
    setGroups((prev) => prev.map((g) => (g.id === groupId ? { ...g, ...updates } : g)))
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

  // Selection

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

  // Bulk ops

  // Applies `transform` to the selected, non-excluded, in-scope files of every group matching
  // `inScope`, then saves those groups.
  const applyToSelected = (
    inScope: (groupId: string) => boolean,
    selectionId: string,
    transform: (f: EditableFileState) => EditableFileState,
  ) => {
    const sel = selections[selectionId] ?? new Set<string>()
    setGroups((prev) => {
      const newGroups = prev.map((g) => {
        if (!inScope(g.id)) return g
        return {
          ...g,
          files: g.files.map((f) => {
            if (!sel.has(f.relative_path) || f.excluded || f.outOfScope) return f
            return transform(f)
          }),
        }
      })
      const toSave = newGroups.filter((g) => inScope(g.id))
      if (toSave.length > 0) notifyGroupChange(toSave)
      return newGroups
    })
  }

  const selectionIdFor = (scope: BulkScope) =>
    Array.isArray(scope) ? MULTI_GROUP_ID : (scope ?? ALL_GROUP_ID)

  const inScopeFor = (scope: BulkScope) =>
    Array.isArray(scope)
      ? (id: string) => scope.includes(id)
      : (id: string) => scope === null || id === scope

  const bulkUpdateFiles = (
    scope: BulkScope,
    transform: (f: EditableFileState) => EditableFileState,
  ) => applyToSelected(inScopeFor(scope), selectionIdFor(scope), transform)

  const exclude = (f: EditableFileState) => ({ ...f, excluded: true })

  const selectedInScope = (scope: BulkScope) => {
    const sel = selections[selectionIdFor(scope)] ?? new Set<string>()
    const inScope = inScopeFor(scope)
    return groups
      .filter((g) => inScope(g.id))
      .flatMap((g) => g.files)
      .filter((f) => sel.has(f.relative_path) && !f.excluded && !f.outOfScope)
  }

  const patchFiles = (
    paths: Set<string>,
    transform: (f: EditableFileState) => EditableFileState,
  ) => {
    setGroups((prev) =>
      prev.map((g) =>
        g.files.some((f) => paths.has(f.relative_path))
          ? { ...g, files: g.files.map((f) => (paths.has(f.relative_path) ? transform(f) : f)) }
          : g,
      ),
    )
  }

  const bulkExclude = (scope: BulkScope) => {
    bulkUpdateFiles(scope, exclude)
    deselectAll(selectionIdFor(scope))
  }

  // Subgroup ops

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

  // Derived values

  const isAllTab = activeTab === ALL_TAB
  const activeGroup = isAllTab ? null : (groups[activeTab] ?? null)
  const activeGroupId = isAllTab ? ALL_GROUP_ID : (activeGroup?.id ?? '')

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
    toggleFileSelection,
    selectAllVisible,
    deselectAll,
    selectedInScope,
    patchFiles,
    bulkExclude,
    clearSubgroupLabel,
    renameSubgroup,
    isAllTab,
    activeGroup,
    activeGroupId,
  }
}
