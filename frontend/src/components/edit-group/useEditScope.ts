import { useMemo } from 'react'
import { applyFileFilter, type FileFilter } from '@/components/import/fileFilter'
import { MULTI_GROUP_ID, type BulkScope } from '@/hooks/useFileEditing'
import type { EditableGroupState } from '@/types'

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
    () =>
      isMultiSelect
        ? groups.filter((g) => selectedGroupIds.has(g.id))
        : isAllTab
          ? groups
          : activeGroup
            ? [activeGroup]
            : [],
    [isMultiSelect, isAllTab, groups, selectedGroupIds, activeGroup],
  )

  const selectedGroupIdArray = useMemo(() => [...selectedGroupIds], [selectedGroupIds])
  const bulkScope: BulkScope = isMultiSelect
    ? selectedGroupIdArray
    : isAllTab
      ? null
      : activeGroupId

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

  const subgroups = useMemo(
    () =>
      [
        ...new Set(
          inScopeFiles.filter((f) => !f.excluded && f.subgroup).map((f) => f.subgroup as string),
        ),
      ].sort(),
    [inScopeFiles],
  )

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
