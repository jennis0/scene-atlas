import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { DndContext, DragOverlay } from '@dnd-kit/core'
import { AlertCircle, Loader2 } from 'lucide-react'
import { Dialog, DialogContent } from '@/components/ui/dialog'
import type { EditableFileState, EditableGroupState, SeedImage } from '@/types'
import { FileCard } from './import/FileCard'
import { FileToolbar } from './import/FileToolbar'
import { MetadataForm } from './import/MetadataForm'
import { EMPTY_FILTER } from './import/fileFilter'
import { useFileEditing, ALL_TAB, MULTI_GROUP_ID } from '@/hooks/useFileEditing'
import { useEditGroupLoad } from '@/hooks/useEditGroupLoad'
import { useEditGroupOperations } from '@/hooks/useEditGroupOperations'
import { useEditGroupDnd } from '@/hooks/useEditGroupDnd'
import { useGroupSidebarMultiselect } from '@/hooks/useGroupSidebarMultiselect'
import { DraggableFileCardWrapper, DragOverlayContent } from './import/shared/dnd'
import { EditGroupHeader } from './edit-group/EditGroupHeader'
import { EditGroupSidebar } from './edit-group/EditGroupSidebar'
import { BulkEditConfirm } from './edit-group/BulkEditConfirm'
import { useMetadataSave } from './edit-group/useMetadataSave'
import { useRefreshLoaded } from './edit-group/useRefreshLoaded'
import { useSortedOutCounts } from './edit-group/useSortedOut'
import { SortedOutStrip } from './edit-group/SortedOutStrip'
import { BulkPanel, SCOPE_FACETS_KEY } from './edit-group/BulkPanel'
import { useBulkImageEdit } from '@/hooks/useBulkImageEdit'
import { gridLabel } from '@/lib/bulkEdit'
import { EditGroupFileGrid } from './edit-group/EditGroupFileGrid'
import { EditGroupFooter } from './edit-group/EditGroupFooter'
import { EditGroupConfirmDialogs } from './edit-group/EditGroupConfirmDialogs'
import type { PendingConfirm } from './edit-group/pendingConfirm'
import { useEditScope } from './edit-group/useEditScope'
import { EditGroupContext, type EditGroupContextValue } from './edit-group/EditGroupContext'
import { invalidateGalleryQueries } from '@/lib/queryKeys'
import { ImportRunningStrip } from './edit-group/ImportRunningStrip'

/** Import-review mode: several groups by ID, all images in scope (e.g. every group an
 * import created, from the import report). */
export interface ImportReview {
  groupIds: number[]
  /** The group to open on, instead of all groups */
  startGroupId?: number
  /** The import the groups came from, to follow while it runs */
  jobId?: string
  /** Add groups the import finished since the editor opened */
  onAddGroups?: (groupIds: number[]) => void
  /** Leave the editor for the import's progress */
  onShowProgress?: (jobId: string) => void
}

interface EditGroupDialogProps {
  // Single-group mode: pass groupId
  groupId?: number | null
  // Mass-edit mode: pass seedImages (the search result images to edit)
  seedImages?: SeedImage[]
  importReview?: ImportReview
  open: boolean
  onClose: () => void
  /** Called after editing is done (changes are auto-saved as you go). */
  onSave: () => void
}

export default function EditGroupDialog({
  groupId,
  seedImages,
  importReview,
  open,
  onClose,
  onSave,
}: EditGroupDialogProps) {
  const groupIds = importReview?.groupIds
  const queryClient = useQueryClient()
  const groupNameRef = useRef<HTMLInputElement>(null)
  const [pending, setPending] = useState<PendingConfirm | null>(null)

  const invalidateGallery = useCallback(() => invalidateGalleryQueries(queryClient), [queryClient])

  // Use a ref to break the circular dependency between useFileEditing
  // (needs autoSaveGroup in onGroupChange) and useEditGroupOperations
  // (needs groups/setGroups from useFileEditing).
  const autoSaveRef = useRef<(group: EditableGroupState) => void>(() => {})

  const {
    groups,
    setGroups,
    activeTab,
    setActiveTab,
    selections,
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
  } = useFileEditing({
    onGroupChange: (affected) => affected.forEach((g) => autoSaveRef.current(g)),
  })

  const { selectedGroupIds, handleGroupClick, resetMultiselect } = useGroupSidebarMultiselect({
    groups,
    onSelectTab: setActiveTab,
  })

  const ops = useEditGroupOperations({
    groupId,
    groups,
    setGroups,
    activeTab,
    setActiveTab,
    selections,
    deselectAll,
    invalidateGallery,
    onSave,
    onClose,
  })
  autoSaveRef.current = ops.autoSaveGroup
  const { saving } = ops

  const dnd = useEditGroupDnd({
    groups,
    selections,
    selectedGroupIds,
    updateFilesInGroup,
    handleMoveImagesToGroup: ops.handleMoveImagesToGroup,
  })

  // Reset dialog-local state (everything NOT owned by useEditGroupLoad or useFileEditing)
  const { resetOperations } = ops
  const { resetDnd } = dnd
  const resetDialogState = useCallback(() => {
    resetOperations()
    resetDnd()
    resetMultiselect()
    setPending(null)
  }, [resetOperations, resetDnd, resetMultiselect])

  const {
    loading,
    loadError,
    isMassEdit,
    ungroupedCount,
    pendingGroups,
    prioritizeGroup,
    awaitedGroupId,
    isLargeReview,
    groupOrder,
  } = useEditGroupLoad({
    open,
    groupId,
    seedImages,
    groupIds,
    startGroupId: importReview?.startGroupId,
    onResetDialogState: resetDialogState,
    fileEditing: {
      groups,
      setGroups,
      setActiveTab,
      setFileFilter,
      setEditingSvHeading,
      setTagVocab,
      setAuthorSuggestions,
    },
  })

  const isImportReview = !!groupIds && groupIds.length > 0

  const showImportProgress =
    importReview?.jobId && importReview.onShowProgress
      ? () => {
          onSave()
          importReview.onShowProgress?.(importReview.jobId!)
        }
      : undefined

  // Called on any close action — changes have already been auto-saved
  const handleDone = useCallback(() => {
    onSave()
    onClose()
  }, [onSave, onClose])

  const scope = useEditScope({
    groups,
    activeGroup,
    activeGroupId,
    isAllTab,
    selectedGroupIds,
    fileFilter,
  })
  const { isMultiSelect, showsMultipleGroups, selectionId, bulkScope } = scope

  // Large import review: All is a panel of server-side counts and bulk edits, not a grid
  const showBulkPanel = isLargeReview && isAllTab && !isMultiSelect
  const refreshLoaded = useRefreshLoaded(groups, patchFiles)
  const bulk = useBulkImageEdit({
    selectedInScope,
    patchFiles,
    refreshLoaded,
    onSaved: () => {
      invalidateGallery()
      void queryClient.invalidateQueries({ queryKey: [SCOPE_FACETS_KEY] })
    },
  })

  // Reset file filter and selections when multi-select composition changes
  const multiSelectKey = useMemo(() => [...selectedGroupIds].sort().join(','), [selectedGroupIds])
  useEffect(() => {
    if (isMultiSelect) {
      setFileFilter(EMPTY_FILTER)
      deselectAll(MULTI_GROUP_ID)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [multiSelectKey])

  const sortedOut = useSortedOutCounts(open)
  const context = useMemo<EditGroupContextValue>(
    () => ({
      groups,
      selectedGroupIds,
      clearSelection: resetMultiselect,
      pending,
      setPending,
      activeDrag: dnd.activeDrag,
      ops,
      sortedOut,
    }),
    [groups, selectedGroupIds, resetMultiselect, pending, dnd.activeDrag, ops, sortedOut],
  )

  // Groups created in the editor have uuid keys and no server id
  const activeGroupDbId =
    activeGroup && !Number.isNaN(Number(activeGroup.id)) ? Number(activeGroup.id) : null
  const activeSelection = selections[selectionId] ?? new Set<string>()
  const hasActiveFilter = !!fileFilter.text || fileFilter.active.length > 0
  const isOriginalGroup = !showsMultipleGroups && !isMassEdit && activeGroup?.id === String(groupId)

  const totalInScope =
    groups.reduce((s, g) => s + g.files.filter((f) => !f.outOfScope && !f.excluded).length, 0) +
    // Large review: groups not opened yet count from their summaries
    (isLargeReview ? pendingGroups.reduce((n, g) => n + g.image_count, 0) : 0)

  const metadata = useMetadataSave({
    scopeGroups: scope.scopeGroups,
    showsMultipleGroups,
    autoSaveGroup: ops.autoSaveGroup,
    onSaved: invalidateGallery,
  })

  const setAuthor = (author: string) => {
    metadata.markDirty()
    if (showsMultipleGroups) {
      setGroups((prev) =>
        prev.map((g) => (!isMultiSelect || selectedGroupIds.has(g.id) ? { ...g, author } : g)),
      )
    } else {
      updateGroup(activeGroupId, { author })
    }
  }

  const renderCard = (file: EditableFileState) => (
    <DraggableFileCardWrapper
      key={file.relative_path}
      file={file}
      groupId={
        showsMultipleGroups ? (scope.fileGroupIds.get(file.relative_path) ?? '') : activeGroupId
      }
      isDndEnabled={!file.excluded && !file.outOfScope}
    >
      <FileCard
        file={file}
        vocab={tagVocab}
        existingSubgroups={scope.subgroups}
        selected={activeSelection.has(file.relative_path)}
        onToggleSelect={() => toggleFileSelection(selectionId, file.relative_path)}
        onUpdate={(updates) =>
          showsMultipleGroups
            ? updateFileAnyGroup(file.relative_path, updates)
            : updateFile(activeTab, file.relative_path, updates)
        }
        excludeTooltip={isMassEdit ? 'Remove from group' : 'Mark for deletion'}
      />
    </DraggableFileCardWrapper>
  )

  return (
    <EditGroupContext.Provider value={context}>
      <Dialog
        open={open}
        onOpenChange={(o) => {
          if (!o && !saving) onClose()
        }}
      >
        <DialogContent
          data-testid="edit-group-dialog"
          aria-label={isMassEdit ? 'Edit search results' : 'Edit group'}
          className="max-w-5xl h-[85vh] overflow-hidden flex flex-col p-0 gap-0"
        >
          <EditGroupHeader
            isMassEdit={isMassEdit}
            summary={
              isMassEdit && !loading && !loadError && groups.length > 0
                ? { images: totalInScope, groups: groups.length, ungrouped: ungroupedCount }
                : null
            }
            onDone={handleDone}
            saving={saving}
          />

          {importReview?.jobId && (
            <ImportRunningStrip
              jobId={importReview.jobId}
              reviewedGroupIds={importReview.groupIds}
              onAddGroups={importReview.onAddGroups}
              onShowProgress={showImportProgress}
            />
          )}

          {loading && (
            <div className="flex items-center justify-center flex-1">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          )}

          {!loading && loadError && (
            <div className="mx-6 mt-4 flex items-center gap-2 text-sm text-destructive bg-destructive/10 border border-destructive/30 rounded-lg px-3 py-2">
              <AlertCircle className="h-4 w-4 flex-shrink-0" />
              {loadError}
            </div>
          )}

          {!loading && !loadError && groups.length > 0 && (
            <DndContext
              sensors={dnd.sensors}
              onDragStart={dnd.handleDragStart}
              onDragEnd={dnd.handleDragEnd}
            >
              <div className="flex min-h-0 flex-1 overflow-hidden">
                {(groups.length > 1 || pendingGroups.length > 0) && (
                  <EditGroupSidebar
                    order={groupOrder}
                    pending={{
                      groups: pendingGroups,
                      awaitedId: awaitedGroupId,
                      onOpen: prioritizeGroup,
                      onDemand: isLargeReview,
                    }}
                    activeTab={activeTab}
                    allTab={{
                      active: isAllTab,
                      count: totalInScope,
                      onSelect: () => setActiveTab(ALL_TAB),
                    }}
                    onGroupClick={handleGroupClick}
                    hasGroupActions={isMassEdit || isImportReview}
                  />
                )}

                <div className="flex-1 min-w-0 flex flex-col overflow-hidden">
                  {showBulkPanel ? (
                    <BulkPanel groupIds={groupIds!} vocab={tagVocab} bulk={bulk} />
                  ) : (
                    <>
                      <div className="px-5 pt-4 pb-3 border-b border-border/30 shrink-0">
                        <MetadataForm
                          author={scope.scopeAuthor}
                          groupName={showsMultipleGroups ? '' : (activeGroup?.group_name ?? '')}
                          authorPlaceholder={
                            isMultiSelect && !scope.scopeAuthor
                              ? 'Multiple — type to set for selected groups'
                              : isAllTab && !scope.scopeAuthor
                                ? 'Multiple — type to set for all groups'
                                : 'Author name'
                          }
                          groupNamePlaceholder={
                            isMultiSelect
                              ? `— (${selectedGroupIds.size} groups selected)`
                              : isAllTab
                                ? '— (select a group to rename)'
                                : 'Group name'
                          }
                          groupNameDisabled={showsMultipleGroups}
                          isMassEdit={isMassEdit}
                          isAllTab={showsMultipleGroups}
                          authorSuggestions={authorSuggestions}
                          suggestionsListId="author-suggestions-edit"
                          onAuthorChange={setAuthor}
                          onGroupNameChange={(val) => {
                            if (showsMultipleGroups) return
                            metadata.markDirty()
                            updateGroup(activeGroupId, { group_name: val })
                          }}
                          onBlur={() => void metadata.save()}
                          groupNameRef={groupNameRef}
                        />
                      </div>

                      {!showsMultipleGroups && activeGroupDbId !== null && (
                        <div className="px-5 shrink-0">
                          <SortedOutStrip
                            groupId={activeGroupDbId}
                            count={sortedOut.counts[activeGroupDbId] ?? 0}
                            onIncluded={sortedOut.refresh}
                          />
                        </div>
                      )}

                      <div className="px-5 shrink-0">
                        <FileToolbar
                          files={scope.inScopeFiles}
                          filteredFiles={scope.filteredFiles}
                          selection={activeSelection}
                          filter={fileFilter}
                          vocab={tagVocab}
                          onFilterChange={setFileFilter}
                          onSelectAll={() => selectAllVisible(selectionId, scope.filteredFiles)}
                          onDeselectAll={() => deselectAll(selectionId)}
                          onBulkAddTag={(tag) =>
                            bulk.request(bulkScope, {
                              addTags: [tag],
                              label: `Add tag "${tag.value}"`,
                            })
                          }
                          onBulkSetGrid={(gridded, gridType) =>
                            bulk.request(bulkScope, {
                              changes: { gridded, grid_type: gridType },
                              label: gridLabel(gridded, gridType),
                            })
                          }
                          onBulkSetImageType={(v) =>
                            bulk.request(bulkScope, {
                              changes: { image_type: v },
                              label: `Set type to ${v === 'scene' ? 'scene' : 'map'}`,
                            })
                          }
                          onBulkSetSubgroup={(v) => {
                            const subgroup = v.trim() || null
                            bulk.request(bulkScope, {
                              changes: { subgroup },
                              label: subgroup ? `Set subgroup to "${subgroup}"` : 'Clear subgroup',
                            })
                          }}
                          onBulkExclude={() => bulkExclude(bulkScope)}
                          onMoveToNewGroup={
                            !showsMultipleGroups && !isMassEdit && activeGroup?.id
                              ? async () => {
                                  await ops.moveToNewGroup(activeGroup.id)
                                  groupNameRef.current?.focus()
                                }
                              : undefined
                          }
                          excludeLabel={isMassEdit ? 'Remove' : 'Delete'}
                          alwaysShowTypeToggle
                        />
                        {showsMultipleGroups && pendingGroups.length > 0 && (
                          <p role="status" className="pb-2 text-xs text-muted-foreground">
                            Still loading {pendingGroups.length} of{' '}
                            {groups.length + pendingGroups.length} groups. Changes here apply to the
                            groups already loaded.
                          </p>
                        )}
                      </div>

                      <EditGroupFileGrid
                        files={scope.filteredFiles}
                        outOfScopeFiles={scope.outOfScopeFiles}
                        renderCard={renderCard}
                        hasActiveFilter={hasActiveFilter}
                        subgroups={{
                          existing: scope.subgroups,
                          canEdit: !showsMultipleGroups,
                          editing: editingSvHeading,
                          setEditing: setEditingSvHeading,
                          rename: (from, to) => renameSubgroup(activeGroup!.id, from, to),
                          clear: (subgroup) => clearSubgroupLabel(activeGroup!.id, subgroup),
                        }}
                        vocab={tagVocab}
                        onUpdateOutOfScope={(file, updates) =>
                          updateFile(activeTab, file.relative_path, updates)
                        }
                      />
                    </>
                  )}

                  <EditGroupFooter
                    showGroupActions={isOriginalGroup}
                    onDone={handleDone}
                    primaryDone={isImportReview}
                  />
                </div>
              </div>

              <DragOverlay dropAnimation={null} modifiers={dnd.dragModifiers}>
                <DragOverlayContent activeDrag={dnd.activeDrag} />
              </DragOverlay>
            </DndContext>
          )}
        </DialogContent>

        <BulkEditConfirm bulk={bulk} />
        <EditGroupConfirmDialogs
          groupId={groupId}
          activeGroup={activeGroup ?? undefined}
          dragMerge={{
            sourceIds: dnd.dragMergeSourceIds,
            target: dnd.dragMergeTarget,
            clear: () => {
              dnd.setDragMergeSourceIds(null)
              dnd.setDragMergeTarget(null)
            },
          }}
        />
      </Dialog>
    </EditGroupContext.Provider>
  )
}
