import { useState, useEffect, useMemo } from 'react'
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

  // ── CRUD ──────────────────────────────────────────────────────────

  const updateGroup = (index: number, updates: Partial<EditableGroupState>) => {
    setGroups((prev) => prev.map((g, i) => (i === index ? { ...g, ...updates } : g)))
  }

  const updateFile = (
    groupIndex: number,
    relativePath: string,
    updates: Partial<EditableFileState>,
  ) => {
    // Compute inline (not functional form) so onGroupChange receives the updated object
    const currentGroup = groups[groupIndex]
    if (!currentGroup) return
    const newGroup = {
      ...currentGroup,
      files: currentGroup.files.map((f) =>
        f.relative_path === relativePath ? { ...f, ...updates } : f,
      ),
    }
    setGroups((prev) => prev.map((g, i) => (i === groupIndex ? newGroup : g)))
    onGroupChange?.([newGroup])
  }

  const updateFileAnyGroup = (relativePath: string, updates: Partial<EditableFileState>) => {
    const newGroups = groups.map((g) => ({
      ...g,
      files: g.files.map((f) => (f.relative_path === relativePath ? { ...f, ...updates } : f)),
    }))
    setGroups(newGroups)
    const affected = newGroups.filter((g) => g.files.some((f) => f.relative_path === relativePath))
    onGroupChange?.(affected)
  }

  const updateFilesInGroup = (
    groupId: string,
    paths: string[],
    updates: Partial<EditableFileState>,
  ) => {
    const currentGroup = groups.find((g) => g.id === groupId)
    if (!currentGroup) return
    const pathSet = new Set(paths)
    const newGroup = {
      ...currentGroup,
      files: currentGroup.files.map((f) =>
        pathSet.has(f.relative_path) ? { ...f, ...updates } : f,
      ),
    }
    setGroups((prev) => prev.map((g) => (g.id === groupId ? newGroup : g)))
    onGroupChange?.([newGroup])
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
    const newGroups = groups.map((g) => {
      if (groupId !== null && g.id !== groupId) return g
      return {
        ...g,
        files: g.files.map((f) => {
          if (!sel.has(f.relative_path) || f.excluded || f.outOfScope) return f
          return transform(f)
        }),
      }
    })
    setGroups(newGroups)
    const toSave = groupId !== null ? newGroups.filter((g) => g.id === groupId) : newGroups
    onGroupChange?.(toSave)
  }

  const bulkAddTag = (groupId: string | null, tag: TagData) => {
    const selId = groupId ?? ALL_GROUP_ID
    const sel = selections[selId] ?? new Set<string>()
    const newGroups = groups.map((g) => {
      if (groupId !== null && g.id !== groupId) return g
      return {
        ...g,
        files: g.files.map((f) => {
          if (!sel.has(f.relative_path) || f.excluded || f.outOfScope) return f
          if (f.tags.some((t) => t.category === tag.category && t.value === tag.value)) return f
          return { ...f, tags: [...f.tags, tag] }
        }),
      }
    })
    setGroups(newGroups)
    const toSave = groupId !== null ? newGroups.filter((g) => g.id === groupId) : newGroups
    onGroupChange?.(toSave)
  }

  const bulkSetGrid = (groupId: string | null, gridded: boolean | null, gridType: string | null) =>
    bulkUpdateFiles(groupId, (f) => ({ ...f, gridded, grid_type: gridType }))

  const bulkSetImageType = (groupId: string | null, value: 'battlemap' | 'scene') =>
    bulkUpdateFiles(groupId, (f) => ({ ...f, image_type: value }))

  const bulkSetSubgroup = (groupId: string | null, value: string) =>
    bulkUpdateFiles(groupId, (f) => ({ ...f, subgroup: value.trim() || null }))

  const bulkExclude = (groupId: string | null) => {
    const selId = groupId ?? ALL_GROUP_ID
    const sel = selections[selId] ?? new Set<string>()
    const newGroups = groups.map((g) => {
      if (groupId !== null && g.id !== groupId) return g
      return {
        ...g,
        files: g.files.map((f) =>
          !sel.has(f.relative_path) || f.outOfScope ? f : { ...f, excluded: true },
        ),
      }
    })
    setGroups(newGroups)
    deselectAll(selId)
    const toSave = groupId !== null ? newGroups.filter((g) => g.id === groupId) : newGroups
    onGroupChange?.(toSave)
  }

  // ── Subgroup ops ──────────────────────────────────────────────────

  const clearSubgroupLabel = (groupId: string, subgroup: string) => {
    const newGroups = groups.map((g) => {
      if (g.id !== groupId) return g
      return {
        ...g,
        files: g.files.map((f) =>
          f.subgroup === subgroup && !f.excluded && !f.outOfScope ? { ...f, subgroup: null } : f,
        ),
      }
    })
    setGroups(newGroups)
    const updated = newGroups.find((g) => g.id === groupId)
    if (updated) onGroupChange?.([updated])
  }

  const renameSubgroup = (groupId: string, oldVal: string, newVal: string) => {
    const newGroups = groups.map((g) => {
      if (g.id !== groupId) return g
      return {
        ...g,
        files: g.files.map((f) =>
          f.subgroup === oldVal && !f.excluded && !f.outOfScope
            ? { ...f, subgroup: newVal.trim() || null }
            : f,
        ),
      }
    })
    setGroups(newGroups)
    const updated = newGroups.find((g) => g.id === groupId)
    if (updated) onGroupChange?.([updated])
  }

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
