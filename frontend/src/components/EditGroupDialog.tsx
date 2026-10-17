import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { DndContext, DragOverlay } from '@dnd-kit/core'
import { AlertCircle, Loader2, X, Pencil } from 'lucide-react'
import { Dialog, DialogContent } from '@/components/ui/dialog'
import type { EditableFileState, EditableGroupState, SeedImage } from '@/types'
import { FileCard } from './import/FileCard'
import { FileToolbar } from './import/FileToolbar'
import { MetadataForm } from './import/MetadataForm'
import { applyFileFilter, EMPTY_FILTER } from './import/fileFilter'
import { useFileEditing, ALL_TAB, MULTI_GROUP_ID, type BulkScope } from '@/hooks/useFileEditing'
import { useEditGroupLoad } from '@/hooks/useEditGroupLoad'
import { useEditGroupOperations } from '@/hooks/useEditGroupOperations'
import { useEditGroupDnd } from '@/hooks/useEditGroupDnd'
import { useGroupSidebarMultiselect } from '@/hooks/useGroupSidebarMultiselect'
import { DraggableFileCardWrapper, DragOverlayContent } from './import/shared/dnd'
import { EditGroupSidebar } from './edit-group/EditGroupSidebar'
import { EditGroupFileGrid } from './edit-group/EditGroupFileGrid'
import { EditGroupFooter } from './edit-group/EditGroupFooter'
import { EditGroupConfirmDialogs } from './edit-group/EditGroupConfirmDialogs'
import type { PendingConfirm } from './edit-group/pendingConfirm'
import { invalidateGalleryQueries } from '@/lib/queryKeys'

interface EditGroupDialogProps {
  // Single-group mode: pass groupId
  groupId?: number | null
  // Mass-edit mode: pass seedImages (the search result images to edit)
  seedImages?: SeedImage[]
  // Import-review mode: pass groupIds to load multiple groups by ID, all images in scope
  // (e.g. every group an import created, from the import report).
  groupIds?: number[]
  open: boolean
  onClose: () => void
  /** Called after editing is done (changes are auto-saved as you go). */
  onSave: () => void
}

export default function EditGroupDialog({
  groupId,
  seedImages,
  groupIds,
  open,
  onClose,
  onSave,
}: EditGroupDialogProps) {
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
  const { saving, merging, groupSaving, groupSaved } = ops

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

  const { loading, loadError, isMassEdit, ungroupedCount } = useEditGroupLoad({
    open,
    groupId,
    seedImages,
    groupIds,
    onResetDialogState: resetDialogState,
    fileEditing: {
      setGroups,
      setActiveTab,
      setFileFilter,
      setEditingSvHeading,
      setTagVocab,
      setAuthorSuggestions,
    },
  })

  const isImportReview = !!groupIds && groupIds.length > 0

  // Called on any close action — changes have already been auto-saved
  const handleDone = useCallback(() => {
    onSave()
    onClose()
  }, [onSave, onClose])

  const isMultiSelect = selectedGroupIds.size >= 2
  const effectiveActiveGroupId = isMultiSelect ? MULTI_GROUP_ID : activeGroupId
  const selectedGroupIdArray = useMemo(() => [...selectedGroupIds], [selectedGroupIds])
  const bulkScope: BulkScope = isMultiSelect
    ? selectedGroupIdArray
    : isAllTab
      ? null
      : activeGroupId

  // Reset file filter and selections when multi-select composition changes
  const multiSelectKey = useMemo(() => [...selectedGroupIds].sort().join(','), [selectedGroupIds])
  useEffect(() => {
    if (isMultiSelect) {
      setFileFilter(EMPTY_FILTER)
      deselectAll(MULTI_GROUP_ID)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [multiSelectKey])

  // Common author across selected groups (for multi-select mode)
  const multiSelectSameAuthor = useMemo(() => {
    if (!isMultiSelect) return ''
    const selected = groups.filter((g) => selectedGroupIds.has(g.id))
    if (selected.length === 0) return ''
    const first = selected[0].author
    return selected.every((g) => g.author === first) ? first : ''
  }, [isMultiSelect, groups, selectedGroupIds])

  // All tab shows only in-scope files; per-group tab shows all (incl. out-of-scope for context)
  const allInScopeFiles = useMemo(
    () => groups.flatMap((g) => g.files.filter((f) => !f.outOfScope)),
    [groups],
  )

  // Multi-select: files from only the selected groups
  const multiSelectFiles = useMemo(
    () =>
      isMultiSelect
        ? groups
            .filter((g) => selectedGroupIds.has(g.id))
            .flatMap((g) => g.files.filter((f) => !f.outOfScope))
        : [],
    [isMultiSelect, groups, selectedGroupIds],
  )

  // Map from file.relative_path → groupId, so cards on the All/multi tab carry their real group ID
  // in drag data (relative_path = String(img.id) in EditGroupDialog context).
  const fileGroupIdMap = useMemo(
    () => new Map(groups.flatMap((g) => g.files.map((f) => [f.relative_path, g.id]))),
    [groups],
  )
  const perGroupFiles = activeGroup?.files ?? []
  const sourceFiles = isMultiSelect ? multiSelectFiles : isAllTab ? allInScopeFiles : perGroupFiles

  // Filtered files: for the in-scope section, filter normally; out-of-scope shown separately
  const inScopeSource = useMemo(() => sourceFiles.filter((f) => !f.outOfScope), [sourceFiles])
  const filteredInScope = useMemo(
    () => applyFileFilter(inScopeSource, fileFilter),
    [inScopeSource, fileFilter],
  )
  const outOfScopeFiles = useMemo(
    () =>
      !isAllTab && !isMultiSelect ? (activeGroup?.files ?? []).filter((f) => f.outOfScope) : [],
    [isAllTab, isMultiSelect, activeGroup],
  )

  const activeSelection = selections[effectiveActiveGroupId] ?? new Set<string>()

  const groupSubVariants = useMemo(
    () =>
      [
        ...new Set(
          inScopeSource.filter((f) => !f.excluded && f.subgroup).map((f) => f.subgroup as string),
        ),
      ].sort(),
    [inScopeSource],
  )

  const hasActiveFilter = !!fileFilter.text || fileFilter.active.length > 0
  const isOriginalGroup =
    !isAllTab && !isMultiSelect && !isMassEdit && activeGroup?.id === String(groupId)
  const showsMultipleGroups = isAllTab || isMultiSelect

  const totalInScope = groups.reduce(
    (s, g) => s + g.files.filter((f) => !f.outOfScope && !f.excluded).length,
    0,
  )

  const scopeGroups = () =>
    isMultiSelect
      ? groups.filter((g) => selectedGroupIds.has(g.id))
      : isAllTab
        ? groups
        : activeGroup
          ? [activeGroup]
          : []

  const setAuthor = (author: string) => {
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
      groupId={showsMultipleGroups ? (fileGroupIdMap.get(file.relative_path) ?? '') : activeGroupId}
      isDndEnabled={!file.excluded && !file.outOfScope}
    >
      <FileCard
        file={file}
        vocab={tagVocab}
        existingSubgroups={groupSubVariants}
        selected={activeSelection.has(file.relative_path)}
        onToggleSelect={() => toggleFileSelection(effectiveActiveGroupId, file.relative_path)}
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
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o && !saving) onClose()
      }}
    >
      <DialogContent
        data-testid="edit-group-dialog"
        className="max-w-5xl h-[85vh] overflow-hidden flex flex-col p-0 gap-0"
      >
        <div className="absolute top-0 inset-x-0 h-0.5 bg-gradient-to-r from-primary/70 via-primary/30 to-transparent pointer-events-none rounded-t-xl" />

        <div className="flex items-center justify-between px-6 pt-6 pb-3 shrink-0">
          <div>
            <h2 className="font-display text-lg font-semibold flex items-center gap-2 text-foreground">
              <Pencil className="h-5 w-5 text-primary shrink-0" />
              {isMassEdit ? 'Edit Search Results' : 'Edit Group'}
            </h2>
            {isMassEdit && !loading && !loadError && groups.length > 0 && (
              <p className="text-[11px] text-muted-foreground/60 mt-0.5 ml-7">
                {totalInScope} image{totalInScope !== 1 ? 's' : ''} across {groups.length} group
                {groups.length !== 1 ? 's' : ''}
                {ungroupedCount > 0 && ` · ${ungroupedCount} ungrouped skipped`}
              </p>
            )}
          </div>
          <button
            onClick={handleDone}
            disabled={saving}
            className="h-7 w-7 rounded flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors disabled:opacity-40"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="h-px bg-gradient-to-r from-primary/60 via-primary/20 to-transparent mx-6 shrink-0" />

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
              {groups.length > 1 && (
                <EditGroupSidebar
                  groups={groups}
                  activeTab={activeTab}
                  isAllTab={isAllTab}
                  onSelectAll={() => setActiveTab(ALL_TAB)}
                  onGroupClick={handleGroupClick}
                  selectedGroupIds={selectedGroupIds}
                  totalInScope={totalInScope}
                  hasGroupActions={isMassEdit || isImportReview}
                  groupSaving={groupSaving}
                  groupSaved={groupSaved}
                  busy={{ saving, merging }}
                  activeDrag={dnd.activeDrag}
                  pending={pending}
                  setPending={setPending}
                  onDeleteGroup={async (id) => {
                    if (await ops.handleDeleteGroup(id)) setPending(null)
                  }}
                  onRemoveGroup={ops.removeGroupFromView}
                />
              )}

              <div className="flex-1 min-w-0 flex flex-col overflow-hidden">
                <div className="px-5 pt-4 pb-3 border-b border-border/30 shrink-0">
                  <MetadataForm
                    author={
                      isMultiSelect
                        ? multiSelectSameAuthor
                        : isAllTab
                          ? allSameAuthor
                          : (activeGroup?.author ?? '')
                    }
                    groupName={showsMultipleGroups ? '' : (activeGroup?.group_name ?? '')}
                    authorPlaceholder={
                      isMultiSelect && !multiSelectSameAuthor
                        ? 'Multiple — type to set for selected groups'
                        : isAllTab && !allSameAuthor
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
                    onGroupNameChange={(val) =>
                      !showsMultipleGroups && updateGroup(activeGroupId, { group_name: val })
                    }
                    onBlur={() => scopeGroups().forEach(ops.autoSaveGroup)}
                    groupNameRef={groupNameRef}
                  />
                </div>

                <div className="px-5 shrink-0">
                  <FileToolbar
                    files={inScopeSource}
                    filteredFiles={filteredInScope}
                    selection={activeSelection}
                    filter={fileFilter}
                    vocab={tagVocab}
                    onFilterChange={setFileFilter}
                    onSelectAll={() => selectAllVisible(effectiveActiveGroupId, filteredInScope)}
                    onDeselectAll={() => deselectAll(effectiveActiveGroupId)}
                    onBulkAddTag={(tag) => bulkAddTag(bulkScope, tag)}
                    onBulkSetGrid={(gridded, gridType) => bulkSetGrid(bulkScope, gridded, gridType)}
                    onBulkSetImageType={(v) => bulkSetImageType(bulkScope, v)}
                    onBulkSetSubgroup={(v) => bulkSetSubgroup(bulkScope, v)}
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
                </div>

                <EditGroupFileGrid
                  files={filteredInScope}
                  outOfScopeFiles={outOfScopeFiles}
                  renderCard={renderCard}
                  hasActiveFilter={hasActiveFilter}
                  activeDrag={dnd.activeDrag}
                  existingSubgroups={groupSubVariants}
                  canEditSubgroups={!showsMultipleGroups}
                  editingSubgroup={editingSvHeading}
                  onEditingSubgroupChange={setEditingSvHeading}
                  onRenameSubgroup={(from, to) => renameSubgroup(activeGroup!.id, from, to)}
                  onClearSubgroup={(subgroup) => clearSubgroupLabel(activeGroup!.id, subgroup)}
                  vocab={tagVocab}
                  onUpdateOutOfScope={(file, updates) =>
                    updateFile(activeTab, file.relative_path, updates)
                  }
                />

                <EditGroupFooter
                  showGroupActions={isOriginalGroup}
                  pending={pending}
                  setPending={setPending}
                  onDelete={async () => {
                    if (!(await ops.handleDelete())) setPending(null)
                  }}
                  onDone={handleDone}
                  saving={saving}
                  merging={merging}
                  saveError={ops.saveError}
                  groupSaving={groupSaving}
                  groupSaved={groupSaved}
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

      <EditGroupConfirmDialogs
        groupId={groupId}
        groups={groups}
        activeGroup={activeGroup ?? undefined}
        selectedGroupIds={selectedGroupIds}
        clearSelection={resetMultiselect}
        pending={pending}
        setPending={setPending}
        dragMerge={{
          sourceIds: dnd.dragMergeSourceIds,
          target: dnd.dragMergeTarget,
          clear: () => {
            dnd.setDragMergeSourceIds(null)
            dnd.setDragMergeTarget(null)
          },
        }}
        ops={ops}
      />
    </Dialog>
  )
}
