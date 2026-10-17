import { useMemo } from 'react'
import { applyFileFilter, type FileFilter } from '@/components/import/fileFilter'
import { MULTI_GROUP_ID, type BulkScope } from '@/hooks/useFileEditing'
import type { EditableFileState, EditableGroupState } from '@/types'

interface UseEditScopeOptions {
  groups: EditableGroupState[]
  activeGroup: EditableGroupState | null
  activeGroupId: string
  isAllTab: boolean
  selectedGroupIds: Set<string>
  fileFilter: FileFilter
}

/** The author shared by every group, or '' when they differ. */
export function commonAuthor(groups: EditableGroupState[]): string {
  const first = groups[0]?.author ?? ''
  return groups.every((g) => g.author === first) ? first : ''
}

interface ScopeMode {
  isMultiSelect: boolean
  isAllTab: boolean
}

/** The groups the dialog is editing: the multi-selection, every group, or the active one. */
function scopeGroupsFor(
  { isMultiSelect, isAllTab }: ScopeMode,
  groups: EditableGroupState[],
  selectedGroupIds: Set<string>,
  activeGroup: EditableGroupState | null,
): EditableGroupState[] {
  if (isMultiSelect) return groups.filter((g) => selectedGroupIds.has(g.id))
  if (isAllTab) return groups
  return activeGroup ? [activeGroup] : []
}

/** What the toolbar's bulk actions apply to (see BulkScope). */
function bulkScopeFor(
  { isMultiSelect, isAllTab }: ScopeMode,
  selectedGroupIds: string[],
  activeGroupId: string,
): BulkScope {
  if (isMultiSelect) return selectedGroupIds
  return isAllTab ? null : activeGroupId
}

/** Sorted subgroup labels used by the in-scope, non-excluded files. */
function subgroupLabels(files: EditableFileState[]): string[] {
  const labels = files.filter((f) => !f.excluded && f.subgroup).map((f) => f.subgroup as string)
  return [...new Set(labels)].sort()
}

/**
 * What the edit dialog is showing: the multi-selected groups, every group (All tab)
 * or the active group, and the files of those groups that are in scope.
 */
export function useEditScope({
  groups,
  activeGroup,
  activeGroupId,
  isAllTab,
  selectedGroupIds,
  fileFilter,
}: UseEditScopeOptions) {
  const isMultiSelect = selectedGroupIds.size >= 2
  const showsMultipleGroups = isAllTab || isMultiSelect

  const scopeGroups = useMemo(
    () => scopeGroupsFor({ isMultiSelect, isAllTab }, groups, selectedGroupIds, activeGroup),
    [isMultiSelect, isAllTab, groups, selectedGroupIds, activeGroup],
  )

  const selectedGroupIdArray = useMemo(() => [...selectedGroupIds], [selectedGroupIds])
  const bulkScope = bulkScopeFor({ isMultiSelect, isAllTab }, selectedGroupIdArray, activeGroupId)

  const inScopeFiles = useMemo(
    () => scopeGroups.flatMap((g) => g.files.filter((f) => !f.outOfScope)),
    [scopeGroups],
  )
  const filteredFiles = useMemo(
    () => applyFileFilter(inScopeFiles, fileFilter),
    [inScopeFiles, fileFilter],
  )
  // Shown for context on a single group's tab only
  const outOfScopeFiles = useMemo(
    () => (showsMultipleGroups ? [] : (activeGroup?.files ?? []).filter((f) => f.outOfScope)),
    [showsMultipleGroups, activeGroup],
  )

  const subgroups = useMemo(() => subgroupLabels(inScopeFiles), [inScopeFiles])

  // Cards on the All/multi tab carry their real group ID in drag data.
  const fileGroupIds = useMemo(
    () => new Map(groups.flatMap((g) => g.files.map((f) => [f.relative_path, g.id]))),
    [groups],
  )

  return {
    isMultiSelect,
    showsMultipleGroups,
    selectionId: isMultiSelect ? MULTI_GROUP_ID : activeGroupId,
    scopeGroups,
    scopeAuthor: commonAuthor(scopeGroups),
    bulkScope,
    inScopeFiles,
    filteredFiles,
    outOfScopeFiles,
    subgroups,
    fileGroupIds,
  }
}
