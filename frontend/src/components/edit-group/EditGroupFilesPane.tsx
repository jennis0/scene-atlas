/**
 * The group editor's files: the toolbar (filter, selection, bulk edits) and the grid of the
 * scope's files, for one group, a multi-selection or All.
 */

import type { ReactNode } from 'react'
import type { EditableFileState } from '@/types'
import type { UseFileEditingReturn } from '@/hooks/useFileEditing'
import type { useBulkImageEdit } from '@/hooks/useBulkImageEdit'
import { gridLabel } from '@/lib/bulkEdit'
import { FileToolbar } from '../import/FileToolbar'
import { EditGroupFileGrid } from './EditGroupFileGrid'
import type { useEditScope } from './useEditScope'

interface EditGroupFilesPaneProps {
  editing: UseFileEditingReturn
  scope: ReturnType<typeof useEditScope>
  bulk: ReturnType<typeof useBulkImageEdit>
  /** The scope's selected files */
  selection: Set<string>
  isMassEdit: boolean
  /** Groups of a review still loading (their files aren't in All yet) */
  loadingGroups: number
  renderCard: (file: EditableFileState) => ReactNode
  /** Split the selection off into a new group (one saved group open) */
  onMoveToNewGroup?: () => Promise<void>
}

export function EditGroupFilesPane({
  editing,
  scope,
  bulk,
  selection,
  isMassEdit,
  loadingGroups,
  renderCard,
  onMoveToNewGroup,
}: EditGroupFilesPaneProps) {
  const { fileFilter, activeGroup, activeTab } = editing
  const { showsMultipleGroups, selectionId, bulkScope } = scope
  const request = (changes: Parameters<typeof bulk.request>[1]) => bulk.request(bulkScope, changes)

  return (
    <>
      <div className="px-5 shrink-0">
        <FileToolbar
          files={scope.inScopeFiles}
          filteredFiles={scope.filteredFiles}
          selection={selection}
          filter={fileFilter}
          vocab={editing.tagVocab}
          onFilterChange={editing.setFileFilter}
          onSelectAll={() => editing.selectAllVisible(selectionId, scope.filteredFiles)}
          onDeselectAll={() => editing.deselectAll(selectionId)}
          onBulkAddTag={(tag) => request({ addTags: [tag], label: `Add tag "${tag.value}"` })}
          onBulkSetGrid={(gridded, gridType) =>
            request({
              changes: { gridded, grid_type: gridType },
              label: gridLabel(gridded, gridType),
            })
          }
          onBulkSetImageType={(v) =>
            request({
              changes: { image_type: v },
              label: `Set type to ${v === 'scene' ? 'scene' : 'map'}`,
            })
          }
          onBulkSetSubgroup={(v) => {
            const subgroup = v.trim() || null
            request({
              changes: { subgroup },
              label: subgroup ? `Set subgroup to "${subgroup}"` : 'Clear subgroup',
            })
          }}
          onBulkExclude={() => editing.bulkExclude(bulkScope)}
          onMoveToNewGroup={onMoveToNewGroup}
          excludeLabel={isMassEdit ? 'Remove' : 'Delete'}
          alwaysShowTypeToggle
        />
        {showsMultipleGroups && loadingGroups > 0 && (
          <p role="status" className="pb-2 text-xs text-muted-foreground">
            Still loading {loadingGroups} of {editing.groups.length + loadingGroups} groups. Changes
            here apply to the groups already loaded.
          </p>
        )}
      </div>

      <EditGroupFileGrid
        files={scope.filteredFiles}
        outOfScopeFiles={scope.outOfScopeFiles}
        renderCard={renderCard}
        hasActiveFilter={!!fileFilter.text || fileFilter.active.length > 0}
        subgroups={{
          existing: scope.subgroups,
          canEdit: !showsMultipleGroups,
          editing: editing.editingSvHeading,
          setEditing: editing.setEditingSvHeading,
          rename: (from, to) => editing.renameSubgroup(activeGroup!.id, from, to),
          clear: (subgroup) => editing.clearSubgroupLabel(activeGroup!.id, subgroup),
        }}
        vocab={editing.tagVocab}
        onUpdateOutOfScope={(file, updates) =>
          editing.updateFile(activeTab, file.relative_path, updates)
        }
      />
    </>
  )
}
