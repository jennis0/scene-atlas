import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { DndContext, DragOverlay } from '@dnd-kit/core'
import {
  AlertCircle,
  Check,
  Loader2,
  X,
  Trash2,
  Search,
  Pencil,
  Merge,
  MoreHorizontal,
  EyeOff,
} from 'lucide-react'
import { Dialog, DialogContent } from '@/components/ui/dialog'
import type { EditableGroupState, SeedImage } from '@/types'
import { MergeGroupPicker } from './MergeGroupPicker'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
} from '@/components/ui/dropdown-menu'
import { FileCard } from './import/FileCard'
import { FileToolbar } from './import/FileToolbar'
import { MetadataForm } from './import/MetadataForm'
import { SubgroupHeading } from './SubgroupHeading'
import { applyFileFilter } from './import/fileFilter'
import { useFileEditing, ALL_TAB } from '@/hooks/useFileEditing'
import { useEditGroupLoad } from '@/hooks/useEditGroupLoad'
import { useEditGroupOperations } from '@/hooks/useEditGroupOperations'
import { useEditGroupDnd } from '@/hooks/useEditGroupDnd'
import { useGroupSidebarMultiselect } from '@/hooks/useGroupSidebarMultiselect'
import {
  DraggableFileCardWrapper,
  DroppableGroupRow,
  DraggableGroupRow,
  DroppableSubgroupSection,
  DragOverlayContent,
} from './import/shared/dnd'
import { GroupSidebarShell } from './import/shared/GroupSidebarShell'
import { QUERY_KEYS } from '@/lib/queryKeys'
import { useImportProgressPolling } from '@/hooks/useImportProgressPolling'

interface EditGroupDialogProps {
  // Single-group mode: pass groupId
  groupId?: number | null
  // Mass-edit mode: pass seedImages (the search result images to edit)
  seedImages?: SeedImage[]
  // Import-review mode: pass groupIds to load multiple groups by ID, all images in scope
  groupIds?: number[]
  // Live import mode: pass importJobId to enable polling and pending-group stubs.
  importJobId?: string
  open: boolean
  onClose: () => void
  /** Called after the import/edit is confirmed.
   *  For live import review, receives the jobId that was confirmed so callers
   *  can dismiss it without relying on external refs that may have been mutated. */
  onSave: (reviewedImportJobId?: string) => void
}

// ── Main component ─────────────────────────────────────────────────────────

export default function EditGroupDialog({
  groupId,
  seedImages,
  groupIds,
  importJobId,
  open,
  onClose,
  onSave,
}: EditGroupDialogProps) {
  const queryClient = useQueryClient()

  // ── Live import review state ────────────────────────────────────────────
  // Grows as groups complete processing; starts from any pre-fetched groupIds.
  const [liveGroupIds, setLiveGroupIds] = useState<number[]>(groupIds ?? [])

  // Reset liveGroupIds whenever the dialog opens with a new importJobId.
  // groupIds is intentionally excluded from the dependency array: in live-review
  // mode it is always undefined, so including it would cause spurious resets
  // if a parent ever re-creates the array reference with identical contents.
  const prevImportJobId = useRef<string | undefined>(undefined)
  useEffect(() => {
    if (importJobId !== prevImportJobId.current) {
      prevImportJobId.current = importJobId
      setLiveGroupIds(groupIds ?? [])
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [importJobId])

  const { runningGroups, failedGroups, allDone } = useImportProgressPolling({
    importJobId,
    onGroupCompleted: (completedGroupId) => setLiveGroupIds((prev) => [...prev, completedGroupId]),
    enabled: open && !!importJobId,
  })

  const invalidateGallery = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: QUERY_KEYS.search })
    queryClient.invalidateQueries({ queryKey: QUERY_KEYS.searchFacets })
  }, [queryClient])

  // ── Shared file editing state and mutations ───────────────────────

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

  // ── Operations (save, merge, delete, split) ─────────────────────
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

  // ── Drag & drop ────────────────────────────────────────────────────
  const dnd = useEditGroupDnd({
    groups,
    selections,
    updateFilesInGroup,
    handleMoveImagesToGroup: ops.handleMoveImagesToGroup,
  })

  // ── Sidebar multiselect ──────────────────────────────────────────────
  const { selectedGroupIds, setSelectedGroupIds, handleGroupClick, resetMultiselect } =
    useGroupSidebarMultiselect({ groups, onSelectTab: setActiveTab })

  // Reset dialog-local state (everything NOT owned by useEditGroupLoad or useFileEditing)
  const { resetOperations } = ops
  const { resetDnd } = dnd
  const resetDialogState = useCallback(() => {
    resetOperations()
    resetDnd()
    resetMultiselect()
  }, [resetOperations, resetDnd, resetMultiselect])

  // ── Data loading (single-group / mass-edit / import-review) ────────
  // In live import mode, pass liveGroupIds (which grows as groups complete);
  // otherwise fall through to the groupIds prop as usual.
  const effectiveGroupIds = importJobId
    ? liveGroupIds.length > 0
      ? liveGroupIds
      : undefined
    : groupIds
  const { loading, loadError, isMassEdit, ungroupedCount } = useEditGroupLoad({
    open,
    groupId,
    seedImages,
    groupIds: effectiveGroupIds,
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

  // ── Close / Done ────────────────────────────────────────────────

  const isImportReview = !!importJobId || (!!groupIds && groupIds.length > 0)

  // Called on any close action — changes have already been auto-saved
  const handleDone = useCallback(() => {
    if (isImportReview) {
      const capturedImportJobId = importJobId
      onSave(capturedImportJobId ?? undefined)
      onClose()
    } else {
      onSave()
      onClose()
    }
  }, [isImportReview, importJobId, onSave, onClose])

  // Destructure commonly-used operations for readability in JSX
  const {
    saving,
    saveError,
    merging,
    groupSaving,
    groupSaved,
    moveToNewGroup,
    handleDelete,
    handleMerge,
    handleDeleteGroup,
    handleMergeGroup,
    removeGroupFromView,
    handleMergeAll,
    handleBulkMerge,
    handleBulkDelete,
    handleDragMergeConfirm,
    confirmingMergeAll,
    setConfirmingMergeAll,
    mergeSourceGroupId,
    setMergeSourceGroupId,
    deleteConfirmGroupId,
    setDeleteConfirmGroupId,
    showMergePicker,
    setShowMergePicker,
    confirmingDelete,
    setConfirmingDelete,
    confirmingBulkMerge,
    setConfirmingBulkMerge,
    confirmingBulkDelete,
    setConfirmingBulkDelete,
  } = ops

  // Destructure DnD values for readability in JSX
  const {
    sensors,
    activeDrag,
    dragMergeSource,
    dragMergeTarget,
    setDragMergeSource,
    setDragMergeTarget,
    handleDragStart,
    handleDragEnd,
  } = dnd

  // ── Derived values ─────────────────────────────────────────────

  // All tab shows only in-scope files; per-group tab shows all (incl. out-of-scope for context)
  const allInScopeFiles = useMemo(
    () => groups.flatMap((g) => g.files.filter((f) => !f.outOfScope)),
    [groups],
  )

  // Map from file.relative_path → groupId, so cards on the All tab carry their real group ID
  // in drag data (relative_path = String(img.id) in EditGroupDialog context).
  const fileGroupIdMap = useMemo(
    () => new Map(groups.flatMap((g) => g.files.map((f) => [f.relative_path, g.id]))),
    [groups],
  )
  const perGroupFiles = activeGroup?.files ?? []
  const sourceFiles = isAllTab ? allInScopeFiles : perGroupFiles

  // Filtered files: for the in-scope section, filter normally; out-of-scope shown separately
  const inScopeSource = useMemo(() => sourceFiles.filter((f) => !f.outOfScope), [sourceFiles])
  const filteredInScope = useMemo(
    () => applyFileFilter(inScopeSource, fileFilter),
    [inScopeSource, fileFilter],
  )
  const outOfScopeFiles = useMemo(
    () => (!isAllTab ? (activeGroup?.files ?? []).filter((f) => f.outOfScope) : []),
    [isAllTab, activeGroup],
  )

  const activeSelection = selections[activeGroupId] ?? new Set<string>()

  const groupSubVariants = useMemo(
    () =>
      [
        ...new Set(
          inScopeSource.filter((f) => !f.excluded && f.subgroup).map((f) => f.subgroup as string),
        ),
      ].sort(),
    [inScopeSource],
  )

  const distinctSubVariants = useMemo(
    () =>
      [...new Set(filteredInScope.map((f) => f.subgroup))].sort((a, b) => {
        if (a === null) return -1
        if (b === null) return 1
        return (a ?? '').localeCompare(b ?? '')
      }),
    [filteredInScope],
  )

  const showSubVariantHeadings = distinctSubVariants.length > 1
  const subVariantGroups = distinctSubVariants.map((sv) => ({
    subVariant: sv,
    files: filteredInScope.filter((f) => f.subgroup === sv),
  }))

  const hasActiveFilter = fileFilter.text || fileFilter.active.length > 0
  const isOriginalGroup = !isAllTab && !isMassEdit && activeGroup?.id === String(groupId)

  const totalInScope = groups.reduce(
    (s, g) => s + g.files.filter((f) => !f.outOfScope && !f.excluded).length,
    0,
  )

  const isBusy = saving || groupSaving.size > 0

  // ── Render ─────────────────────────────────────────────────────

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o && !saving) onClose()
      }}
    >
      <DialogContent className="max-w-5xl h-[85vh] overflow-hidden flex flex-col p-0 gap-0">
        {/* Amber stripe */}
        <div className="absolute top-0 inset-x-0 h-0.5 bg-gradient-to-r from-primary/70 via-primary/30 to-transparent pointer-events-none rounded-t-xl" />

        {/* ── Header ── */}
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
        {/* Amber rule */}
        <div className="h-px bg-gradient-to-r from-primary/60 via-primary/20 to-transparent mx-6 shrink-0" />

        {/* ── Loading ── */}
        {loading && (
          <div className="flex items-center justify-center flex-1">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        )}

        {/* ── Waiting for first group to complete (live import mode, no groups yet) ── */}
        {!loading && !loadError && groups.length === 0 && !!importJobId && !allDone && (
          <div className="flex flex-col items-center justify-center flex-1 gap-3 text-muted-foreground">
            <Loader2 className="h-6 w-6 animate-spin" />
            <p className="text-sm">Waiting for groups to process…</p>
          </div>
        )}

        {/* ── Loading initial groups for completed import (poll hasn't returned yet) ── */}
        {!loading && !loadError && groups.length === 0 && !!importJobId && allDone && (
          <div className="flex items-center justify-center flex-1">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        )}

        {/* ── Load error ── */}
        {!loading && loadError && (
          <div className="mx-6 mt-4 flex items-center gap-2 text-sm text-destructive bg-destructive/10 border border-destructive/30 rounded-lg px-3 py-2">
            <AlertCircle className="h-4 w-4 flex-shrink-0" />
            {loadError}
          </div>
        )}

        {/* ── Main content ── */}
        {!loading && !loadError && groups.length > 0 && (
          <DndContext sensors={sensors} onDragStart={handleDragStart} onDragEnd={handleDragEnd}>
            <div className="flex min-h-0 flex-1 overflow-hidden">
              {/* ── Left: groups nav (only when >1 group, or when stubs are present) ── */}
              {(groups.length > 1 || runningGroups.length > 0 || failedGroups.length > 0) && (
                <GroupSidebarShell
                  headerLabel={`${groups.length + runningGroups.length + failedGroups.length} groups`}
                  allCount={totalInScope}
                  isAllActive={isAllTab}
                  onSelectAll={() => setActiveTab(ALL_TAB)}
                  footer={
                    (isMassEdit || isImportReview) && groups.length >= 2 ? (
                      <div className="p-2.5 border-t border-border/30 shrink-0">
                        {selectedGroupIds.size >= 2 ? (
                          <div className="space-y-1.5">
                            <span className="text-[10px] text-muted-foreground/60 font-semibold uppercase tracking-wider">
                              {selectedGroupIds.size} selected
                            </span>
                            <div className="flex gap-1">
                              <button
                                onClick={() => setConfirmingBulkMerge(true)}
                                disabled={merging || saving}
                                className="flex-1 text-[11px] py-1 rounded border border-border/40 bg-secondary/30 text-muted-foreground hover:bg-secondary/60 hover:text-foreground transition-colors flex items-center justify-center gap-1 disabled:opacity-40"
                              >
                                <Merge className="h-3 w-3" />
                                Merge
                              </button>
                              <button
                                onClick={() => setConfirmingBulkDelete(true)}
                                disabled={merging || saving}
                                className="flex-1 text-[11px] py-1 rounded border border-destructive/30 bg-destructive/5 text-destructive/70 hover:bg-destructive/10 hover:text-destructive transition-colors flex items-center justify-center gap-1 disabled:opacity-40"
                              >
                                <Trash2 className="h-3 w-3" />
                                Delete
                              </button>
                            </div>
                          </div>
                        ) : (
                          <button
                            onClick={() => setConfirmingMergeAll(true)}
                            disabled={merging || saving}
                            className="w-full text-[12px] py-1.5 rounded border border-border/40 bg-secondary/30 text-muted-foreground hover:bg-secondary/60 hover:text-foreground transition-colors flex items-center justify-center gap-1.5 disabled:opacity-40 disabled:cursor-not-allowed"
                          >
                            <Merge className="h-3.5 w-3.5" />
                            {merging ? 'Merging…' : 'Merge All'}
                          </button>
                        )}
                      </div>
                    ) : undefined
                  }
                >
                  {groups.map((g, i) => (
                    <DroppableGroupRow key={g.id} groupId={g.id} activeDrag={activeDrag}>
                      <DraggableGroupRow groupId={g.id} isDndEnabled={isMassEdit || isImportReview}>
                        <div className="group/navrow">
                          {deleteConfirmGroupId === g.id ? (
                            <div className="px-3 py-2 border-l-2 border-destructive/50 bg-destructive/5">
                              <p className="text-[11px] text-destructive/80 mb-1.5">
                                Delete this group?
                              </p>
                              <div className="flex gap-1">
                                <button
                                  onClick={() => handleDeleteGroup(g.id)}
                                  disabled={saving}
                                  className="px-2 py-0.5 rounded border border-destructive/50 bg-destructive/10 text-destructive text-[10px] hover:bg-destructive/20 transition-colors disabled:opacity-50"
                                >
                                  {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : 'Delete'}
                                </button>
                                <button
                                  onClick={() => setDeleteConfirmGroupId(null)}
                                  disabled={saving}
                                  className="px-2 py-0.5 rounded border border-border bg-secondary text-muted-foreground text-[10px] hover:text-foreground transition-colors disabled:opacity-50"
                                >
                                  Cancel
                                </button>
                              </div>
                            </div>
                          ) : (
                            <div
                              className={`flex items-center transition-colors border-l-2 ${
                                selectedGroupIds.has(g.id)
                                  ? 'border-primary/60 bg-primary/15 text-primary'
                                  : activeTab === i
                                    ? 'border-primary bg-primary/10 text-primary'
                                    : 'border-transparent text-muted-foreground hover:text-foreground hover:bg-secondary/50'
                              }`}
                            >
                              <button
                                onClick={(e) => handleGroupClick(i, g.id, e)}
                                className="flex-1 flex items-center gap-2 pl-3 pr-1 py-2 text-left min-w-0"
                              >
                                <span className="flex-1 text-[12px] truncate">{g.group_name}</span>
                                <span className="text-[11px] text-muted-foreground/40 tabular-nums shrink-0 flex items-center gap-1">
                                  {g.files.filter((f) => !f.excluded && !f.outOfScope).length}
                                  {g.files.some((f) => f.outOfScope) && (
                                    <span className="ml-0.5 opacity-50">
                                      +{g.files.filter((f) => f.outOfScope).length}
                                    </span>
                                  )}
                                  {groupSaving.has(g.id) ? (
                                    <Loader2 className="h-3 w-3 animate-spin text-muted-foreground/40 ml-1" />
                                  ) : groupSaved.has(g.id) ? (
                                    <Check className="h-3 w-3 text-emerald-600 dark:text-emerald-400/70 ml-1" />
                                  ) : null}
                                </span>
                              </button>
                              {(isMassEdit || isImportReview) && (
                                <DropdownMenu>
                                  <DropdownMenuTrigger asChild>
                                    <button
                                      className="opacity-0 group-hover/navrow:opacity-100 focus:opacity-100 h-7 w-6 mr-1 flex items-center justify-center rounded text-muted-foreground/50 hover:text-foreground hover:bg-black/5 dark:hover:bg-white/5 transition-all shrink-0"
                                      onClick={(e) => e.stopPropagation()}
                                    >
                                      <MoreHorizontal className="h-3.5 w-3.5" />
                                    </button>
                                  </DropdownMenuTrigger>
                                  <DropdownMenuContent align="end">
                                    <DropdownMenuItem onClick={() => setMergeSourceGroupId(g.id)}>
                                      <Merge className="h-4 w-4 mr-2" />
                                      Merge into…
                                    </DropdownMenuItem>
                                    <DropdownMenuItem onClick={() => removeGroupFromView(g.id)}>
                                      <EyeOff className="h-4 w-4 mr-2" />
                                      Remove from view
                                    </DropdownMenuItem>
                                    <DropdownMenuSeparator />
                                    <DropdownMenuItem
                                      onClick={() => setDeleteConfirmGroupId(g.id)}
                                      className="text-destructive focus:text-destructive"
                                    >
                                      <Trash2 className="h-4 w-4 mr-2" />
                                      Delete group
                                    </DropdownMenuItem>
                                  </DropdownMenuContent>
                                </DropdownMenu>
                              )}
                            </div>
                          )}
                        </div>
                      </DraggableGroupRow>
                    </DroppableGroupRow>
                  ))}

                  {/* ── Pending group stubs (still processing) ── */}
                  {runningGroups.map((stub) => (
                    <div
                      key={stub.group_job_id}
                      className="flex items-center gap-2 pl-3 pr-3 py-2 opacity-60 cursor-not-allowed select-none border-l-2 border-transparent"
                    >
                      <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground shrink-0" />
                      <span className="flex-1 text-[12px] text-muted-foreground truncate">
                        {stub.group_name}
                      </span>
                      <span className="text-[11px] text-muted-foreground/40 tabular-nums shrink-0">
                        {stub.processed_files}/{stub.total_files}
                      </span>
                    </div>
                  ))}

                  {/* ── Failed group stubs ── */}
                  {failedGroups.map((stub) => (
                    <div
                      key={stub.group_job_id}
                      className="flex items-center gap-2 pl-3 pr-3 py-2 opacity-70 select-none border-l-2 border-transparent"
                    >
                      <AlertCircle className="h-3.5 w-3.5 text-destructive shrink-0" />
                      <span className="flex-1 text-[12px] text-muted-foreground truncate">
                        {stub.group_name}
                      </span>
                      <span className="text-[11px] text-destructive/60 shrink-0">
                        {stub.failed_files} failed
                      </span>
                    </div>
                  ))}
                </GroupSidebarShell>
              )}

              {/* ── Right: active group content ── */}
              <div className="flex-1 min-w-0 flex flex-col overflow-hidden">
                {/* Group metadata */}
                <div className="px-5 pt-4 pb-3 border-b border-border/30 shrink-0">
                  <MetadataForm
                    author={isAllTab ? allSameAuthor : (activeGroup?.author ?? '')}
                    groupName={isAllTab ? '' : (activeGroup?.group_name ?? '')}
                    authorPlaceholder={
                      isAllTab && !allSameAuthor
                        ? 'Multiple — type to set for all groups'
                        : 'Author name'
                    }
                    groupNamePlaceholder={isAllTab ? '— (select a group to rename)' : 'Group name'}
                    groupNameDisabled={isAllTab}
                    isMassEdit={isMassEdit}
                    isAllTab={isAllTab}
                    authorSuggestions={authorSuggestions}
                    suggestionsListId="author-suggestions-edit"
                    onAuthorChange={(val) => {
                      if (isAllTab) {
                        setGroups((prev) => prev.map((g) => ({ ...g, author: val })))
                      } else {
                        updateGroup(activeTab, { author: val })
                      }
                    }}
                    onGroupNameChange={(val) =>
                      !isAllTab && updateGroup(activeTab, { group_name: val })
                    }
                    onBlur={() => {
                      if (isAllTab) {
                        groups.forEach(ops.autoSaveGroup)
                      } else if (activeGroup) {
                        ops.autoSaveGroup(activeGroup)
                      }
                    }}
                  />
                </div>

                {/* File toolbar */}
                <div className="px-5 shrink-0">
                  <FileToolbar
                    files={inScopeSource}
                    filteredFiles={filteredInScope}
                    selection={activeSelection}
                    filter={fileFilter}
                    vocab={tagVocab}
                    onFilterChange={setFileFilter}
                    onSelectAll={() => selectAllVisible(activeGroupId, filteredInScope)}
                    onDeselectAll={() => deselectAll(activeGroupId)}
                    onBulkAddTag={(tag) => bulkAddTag(isAllTab ? null : activeGroupId, tag)}
                    onBulkSetGrid={(gridded, gridType) =>
                      bulkSetGrid(isAllTab ? null : activeGroupId, gridded, gridType)
                    }
                    onBulkSetImageType={(v) => bulkSetImageType(isAllTab ? null : activeGroupId, v)}
                    onBulkSetSubgroup={(v) => bulkSetSubgroup(isAllTab ? null : activeGroupId, v)}
                    onBulkExclude={() => bulkExclude(isAllTab ? null : activeGroupId)}
                    onMoveToNewGroup={
                      !isAllTab && !isMassEdit && activeGroup?.id
                        ? () => moveToNewGroup(activeGroup.id)
                        : undefined
                    }
                    excludeLabel={isMassEdit ? 'Remove' : 'Delete'}
                    alwaysShowTypeToggle
                  />
                </div>

                {/* File gallery */}
                <div className="min-h-0 flex-1 overflow-y-auto px-5 py-3">
                  {showSubVariantHeadings ? (
                    subVariantGroups.map((svGroup) => {
                      const nonExcluded = svGroup.files.filter((f) => !f.excluded).length
                      const isEditing =
                        !isAllTab &&
                        editingSvHeading === svGroup.subVariant &&
                        svGroup.subVariant !== null
                      return (
                        <DroppableSubgroupSection
                          key={svGroup.subVariant ?? '__main__'}
                          subVariant={svGroup.subVariant}
                          activeDrag={activeDrag}
                        >
                          <SubgroupHeading
                            subgroup={svGroup.subVariant}
                            count={nonExcluded}
                            isEditing={isEditing}
                            existingSubgroups={groupSubVariants}
                            onStartEdit={() => setEditingSvHeading(svGroup.subVariant!)}
                            onCommit={(val) => {
                              renameSubgroup(activeGroup!.id, svGroup.subVariant!, val)
                              setEditingSvHeading(null)
                            }}
                            onCancel={() => setEditingSvHeading(null)}
                            onClear={() => clearSubgroupLabel(activeGroup!.id, svGroup.subVariant!)}
                            canEdit={!isAllTab}
                          />
                          <div className="grid grid-cols-2 gap-2 pb-2">
                            {svGroup.files.map((file) => (
                              <DraggableFileCardWrapper
                                key={file.relative_path}
                                file={file}
                                groupId={
                                  isAllTab
                                    ? (fileGroupIdMap.get(file.relative_path) ?? '')
                                    : activeGroupId
                                }
                                isDndEnabled={!file.excluded && !file.outOfScope}
                              >
                                <FileCard
                                  file={file}
                                  jobId=""
                                  vocab={tagVocab}
                                  existingSubgroups={groupSubVariants}
                                  selected={activeSelection.has(file.relative_path)}
                                  onToggleSelect={() =>
                                    toggleFileSelection(activeGroupId, file.relative_path)
                                  }
                                  onUpdate={(updates) =>
                                    isAllTab
                                      ? updateFileAnyGroup(file.relative_path, updates)
                                      : updateFile(activeTab, file.relative_path, updates)
                                  }
                                  excludeTooltip={
                                    isMassEdit ? 'Remove from group' : 'Mark for deletion'
                                  }
                                />
                              </DraggableFileCardWrapper>
                            ))}
                          </div>
                        </DroppableSubgroupSection>
                      )
                    })
                  ) : (
                    <div className="grid grid-cols-2 gap-2">
                      {filteredInScope.map((file) => (
                        <DraggableFileCardWrapper
                          key={file.relative_path}
                          file={file}
                          groupId={
                            isAllTab
                              ? (fileGroupIdMap.get(file.relative_path) ?? '')
                              : activeGroupId
                          }
                          isDndEnabled={!file.excluded && !file.outOfScope}
                        >
                          <FileCard
                            file={file}
                            jobId=""
                            vocab={tagVocab}
                            existingSubgroups={groupSubVariants}
                            selected={activeSelection.has(file.relative_path)}
                            onToggleSelect={() =>
                              toggleFileSelection(activeGroupId, file.relative_path)
                            }
                            onUpdate={(updates) =>
                              isAllTab
                                ? updateFileAnyGroup(file.relative_path, updates)
                                : updateFile(activeTab, file.relative_path, updates)
                            }
                            excludeTooltip={isMassEdit ? 'Remove from group' : 'Mark for deletion'}
                          />
                        </DraggableFileCardWrapper>
                      ))}
                    </div>
                  )}

                  {filteredInScope.length === 0 && hasActiveFilter && (
                    <div className="flex flex-col items-center py-12 text-muted-foreground gap-2">
                      <Search className="h-8 w-8 text-muted-foreground/30" />
                      <p className="text-sm">No files match the current filter</p>
                    </div>
                  )}

                  {/* Out-of-scope files — shown in per-group tab only, as context */}
                  {outOfScopeFiles.length > 0 && (
                    <div className="mt-4">
                      <div className="flex items-center gap-2 mb-2">
                        <div className="flex-1 h-px bg-border/20" />
                        <span className="text-[10px] font-semibold text-muted-foreground/40 uppercase tracking-wider whitespace-nowrap">
                          Other images in this group
                        </span>
                        <div className="flex-1 h-px bg-border/20" />
                      </div>
                      <div className="grid grid-cols-2 gap-2">
                        {outOfScopeFiles.map((file) => (
                          <FileCard
                            key={file.relative_path}
                            file={file}
                            jobId=""
                            vocab={tagVocab}
                            existingSubgroups={groupSubVariants}
                            selected={false}
                            onToggleSelect={() => {}}
                            onUpdate={(updates) =>
                              updateFile(activeTab, file.relative_path, updates)
                            }
                          />
                        ))}
                      </div>
                    </div>
                  )}
                </div>

                {/* ── Footer ── */}
                <div className="px-5 py-3 border-t border-border/30 shrink-0 flex items-center justify-between gap-3">
                  {/* Delete group (single-group mode only, for the original persisted group) */}
                  {isOriginalGroup ? (
                    confirmingDelete ? (
                      <div className="flex items-center gap-2 text-sm text-destructive">
                        <span>Delete this group and all its images?</span>
                        <button
                          onClick={handleDelete}
                          disabled={saving}
                          className="px-2.5 py-1 text-xs rounded border border-destructive/50 bg-destructive/10 text-destructive hover:bg-destructive/20 transition-colors disabled:opacity-50"
                        >
                          {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : 'Confirm'}
                        </button>
                        <button
                          onClick={() => setConfirmingDelete(false)}
                          disabled={saving}
                          className="px-2.5 py-1 text-xs rounded border border-border bg-secondary text-muted-foreground hover:text-foreground transition-colors disabled:opacity-50"
                        >
                          Cancel
                        </button>
                      </div>
                    ) : (
                      <div className="flex items-center gap-1">
                        <button
                          onClick={() => setConfirmingDelete(true)}
                          className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs rounded text-destructive/70 hover:text-destructive hover:bg-destructive/10 transition-colors"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                          Delete Group
                        </button>
                        <button
                          onClick={() => setShowMergePicker(true)}
                          disabled={saving || merging}
                          className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs rounded text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors disabled:opacity-50"
                        >
                          <Merge className="h-3.5 w-3.5" />
                          Merge into…
                        </button>
                      </div>
                    )
                  ) : (
                    <div />
                  )}

                  {/* Save status + Done */}
                  <div className="flex items-center gap-2">
                    {saveError && (
                      <span className="text-xs text-destructive flex items-center gap-1 max-w-xs truncate">
                        <AlertCircle className="h-3.5 w-3.5 shrink-0" />
                        {saveError}
                      </span>
                    )}
                    {!saveError && groupSaving.size > 0 && (
                      <span className="text-xs text-muted-foreground/60 flex items-center gap-1">
                        <Loader2 className="h-3 w-3 animate-spin" />
                        Saving…
                      </span>
                    )}
                    {!saveError && groupSaving.size === 0 && groupSaved.size > 0 && (
                      <span className="text-xs text-emerald-600 dark:text-emerald-400/70 flex items-center gap-1">
                        <Check className="h-3 w-3" />
                        Saved
                      </span>
                    )}
                    <button
                      onClick={handleDone}
                      disabled={isBusy}
                      className={
                        isImportReview
                          ? 'px-4 py-1.5 text-sm rounded font-medium bg-primary text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-40'
                          : 'px-3 py-1.5 text-sm rounded border border-primary/40 bg-primary/20 text-primary hover:bg-primary/30 transition-colors disabled:opacity-40'
                      }
                    >
                      {saving ? (
                        <>
                          <Loader2 className="h-3.5 w-3.5 animate-spin inline mr-1" />
                          Working…
                        </>
                      ) : groupSaving.size > 0 ? (
                        <>
                          <Loader2 className="h-3.5 w-3.5 animate-spin inline mr-1" />
                          Saving…
                        </>
                      ) : isImportReview ? (
                        'Confirm Import'
                      ) : (
                        'Done'
                      )}
                    </button>
                  </div>
                </div>
              </div>
            </div>

            {/* ── Drag overlay ── */}
            <DragOverlay dropAnimation={null}>
              <DragOverlayContent activeDrag={activeDrag} />
            </DragOverlay>
          </DndContext>
        )}
      </DialogContent>

      {/* Merge picker — shared for footer (single-group) and nav (mass-edit) actions */}
      <MergeGroupPicker
        open={showMergePicker || mergeSourceGroupId !== null}
        onClose={() => {
          setShowMergePicker(false)
          setMergeSourceGroupId(null)
        }}
        excludeGroupId={mergeSourceGroupId !== null ? Number(mergeSourceGroupId) : groupId}
        onSelect={(target) =>
          mergeSourceGroupId ? handleMergeGroup(mergeSourceGroupId, target) : handleMerge(target)
        }
        currentGroupName={
          mergeSourceGroupId !== null
            ? groups.find((g) => g.id === mergeSourceGroupId)?.group_name
            : activeGroup?.group_name
        }
      />

      {/* Merge all confirmation (mass-edit mode) */}
      <ConfirmDialog
        open={confirmingMergeAll}
        onOpenChange={setConfirmingMergeAll}
        title="Merge All Groups"
        description={`This will merge all ${groups.length} groups into "${groups[0]?.group_name ?? ''}". This cannot be undone.`}
        confirmLabel="Merge All"
        confirmVariant="default"
        loadingLabel="Merging…"
        onConfirm={handleMergeAll}
        isLoading={merging}
      />

      {/* Merge via drag confirmation */}
      <ConfirmDialog
        open={dragMergeSource !== null && dragMergeTarget !== null}
        onOpenChange={(open) => {
          if (!open) {
            setDragMergeSource(null)
            setDragMergeTarget(null)
          }
        }}
        title="Merge Groups"
        description={`Merge "${groups.find((g) => g.id === dragMergeSource)?.group_name ?? ''}" (${groups.find((g) => g.id === dragMergeSource)?.files.filter((f) => !f.excluded).length ?? 0} images) into "${groups.find((g) => g.id === dragMergeTarget)?.group_name ?? ''}"? This cannot be undone.`}
        confirmLabel="Merge"
        confirmVariant="default"
        loadingLabel="Merging…"
        onConfirm={() => {
          if (dragMergeSource && dragMergeTarget) {
            handleDragMergeConfirm(dragMergeSource, dragMergeTarget).then(() => {
              setDragMergeSource(null)
              setDragMergeTarget(null)
            })
          }
        }}
        isLoading={merging}
      />

      {/* Bulk merge confirmation (sidebar multiselect) */}
      <ConfirmDialog
        open={confirmingBulkMerge}
        onOpenChange={setConfirmingBulkMerge}
        title="Merge Selected Groups"
        description={`This will merge ${selectedGroupIds.size} selected groups into "${groups.find((g) => g.id === [...selectedGroupIds][0])?.group_name ?? ''}". This cannot be undone.`}
        confirmLabel="Merge Selected"
        confirmVariant="default"
        loadingLabel="Merging…"
        onConfirm={() =>
          handleBulkMerge(selectedGroupIds).then(() => setSelectedGroupIds(new Set()))
        }
        isLoading={merging}
      />

      {/* Bulk delete confirmation (sidebar multiselect) */}
      <ConfirmDialog
        open={confirmingBulkDelete}
        onOpenChange={setConfirmingBulkDelete}
        title="Delete Selected Groups"
        description={`This will permanently delete ${selectedGroupIds.size} groups and all their images. This cannot be undone.`}
        confirmLabel="Delete All"
        confirmVariant="destructive"
        loadingLabel="Deleting…"
        onConfirm={() =>
          handleBulkDelete(selectedGroupIds).then(() => setSelectedGroupIds(new Set()))
        }
        isLoading={saving}
      />
    </Dialog>
  )
}
