import { useRef, useMemo } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import { Check, AlertCircle, Loader2, SkipForward, Undo2, Search } from 'lucide-react'
import { ImportFileCard } from './ImportFileCard'
import { ImportFileToolbar } from './ImportFileToolbar'
import { MetadataForm } from './MetadataForm'
import { SubgroupHeading } from '@/components/SubgroupHeading'
import type { UseImportStateReturn } from '@/hooks/useImportState'
import type { FileFilter } from './fileFilter'
import type { EditableFileState } from '@/types'

type ImportState = UseImportStateReturn

interface ImportGroupContentProps {
  s: ImportState
}

/** Threshold: only virtualize when file count reaches this */
const VIRTUALIZE_THRESHOLD = 50

/** Estimated heights (px) for the virtualizer */
const CARD_ROW_HEIGHT = 120
const SUBGROUP_HEADING_HEIGHT = 36

// ── Flattened item types for virtualization with subgroup headings ──

type FlatItem =
  | { type: 'heading'; subgroup: string | null; count: number }
  | { type: 'card-row'; files: EditableFileState[] }

function flattenSubgroupItems(
  subgroupGroups: { subgroup: string | null; files: EditableFileState[] }[],
): FlatItem[] {
  const items: FlatItem[] = []
  for (const sg of subgroupGroups) {
    const nonExcluded = sg.files.filter((f) => !f.excluded).length
    items.push({ type: 'heading', subgroup: sg.subgroup, count: nonExcluded })
    // Pair files into 2-column rows
    for (let i = 0; i < sg.files.length; i += 2) {
      items.push({ type: 'card-row', files: sg.files.slice(i, i + 2) })
    }
  }
  return items
}

/** Pair flat files into 2-column rows */
function pairIntoRows(files: EditableFileState[]): EditableFileState[][] {
  const rows: EditableFileState[][] = []
  for (let i = 0; i < files.length; i += 2) {
    rows.push(files.slice(i, i + 2))
  }
  return rows
}

// ── FileGallery: handles both virtualized and non-virtualized rendering ──

interface FileGalleryProps {
  showSubgroupHeadings: boolean
  subgroupGroups: { subgroup: string | null; files: EditableFileState[] }[]
  filteredFiles: EditableFileState[]
  groupSubgroups: string[]
  activeSelection: Set<string>
  activeGroupId: string
  jobId: string
  disabled: boolean
  isAllTab: boolean
  fileFilter: FileFilter
  toggleFileSelection: (groupId: string, relativePath: string) => void
  onUpdateFile: (relativePath: string, updates: Partial<EditableFileState>) => void
}

function FileGallery({
  showSubgroupHeadings,
  subgroupGroups,
  filteredFiles,
  groupSubgroups,
  activeSelection,
  activeGroupId,
  jobId,
  disabled,
  isAllTab,
  fileFilter,
  toggleFileSelection,
  onUpdateFile,
}: FileGalleryProps) {
  const scrollRef = useRef<HTMLDivElement>(null)

  /** Render a 2-col row of ImportFileCards */
  const renderCardRow = (files: EditableFileState[]) => (
    <div className="grid grid-cols-2 gap-2 pb-2">
      {files.map((file) => (
        <ImportFileCard
          key={file.relative_path}
          file={file}
          jobId={jobId}
          existingSubgroups={groupSubgroups}
          selected={activeSelection.has(file.relative_path)}
          onToggleSelect={() => toggleFileSelection(activeGroupId, file.relative_path)}
          onUpdate={(updates) => onUpdateFile(file.relative_path, updates)}
          disabled={disabled}
        />
      ))}
    </div>
  )

  // ── Flat-list virtualization (no subgroup headings) ──

  const flatRows = useMemo(
    () => (showSubgroupHeadings ? [] : pairIntoRows(filteredFiles)),
    [showSubgroupHeadings, filteredFiles],
  )

  const flatVirtualizer = useVirtualizer({
    count: flatRows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => CARD_ROW_HEIGHT,
    overscan: 5,
    enabled: !showSubgroupHeadings && filteredFiles.length >= VIRTUALIZE_THRESHOLD,
  })

  // ── Subgroup-heading virtualization ──

  const subgroupItems = useMemo(
    () => (showSubgroupHeadings ? flattenSubgroupItems(subgroupGroups) : []),
    [showSubgroupHeadings, subgroupGroups],
  )

  const totalSubgroupFiles = useMemo(
    () => (showSubgroupHeadings ? subgroupGroups.reduce((sum, sg) => sum + sg.files.length, 0) : 0),
    [showSubgroupHeadings, subgroupGroups],
  )

  const subgroupVirtualizer = useVirtualizer({
    count: subgroupItems.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: (index) =>
      subgroupItems[index]?.type === 'heading' ? SUBGROUP_HEADING_HEIGHT : CARD_ROW_HEIGHT,
    overscan: 5,
    enabled: showSubgroupHeadings && totalSubgroupFiles >= VIRTUALIZE_THRESHOLD,
  })

  const shouldVirtualizeFlat = !showSubgroupHeadings && filteredFiles.length >= VIRTUALIZE_THRESHOLD
  const shouldVirtualizeSubgroups =
    showSubgroupHeadings && totalSubgroupFiles >= VIRTUALIZE_THRESHOLD

  // ── Empty-state messages ──

  const emptyFilterMessage =
    filteredFiles.length === 0 && (fileFilter.text || fileFilter.active.length > 0)
  const emptyAllTabMessage =
    filteredFiles.length === 0 && !fileFilter.text && fileFilter.active.length === 0 && isAllTab

  // ── Render ──

  return (
    <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto px-5 py-3">
      {/* Virtualized flat list */}
      {shouldVirtualizeFlat && (
        <div
          style={{
            height: `${flatVirtualizer.getTotalSize()}px`,
            position: 'relative',
            width: '100%',
          }}
        >
          {flatVirtualizer.getVirtualItems().map((virtualRow) => (
            <div
              key={virtualRow.key}
              data-index={virtualRow.index}
              ref={flatVirtualizer.measureElement}
              style={{
                position: 'absolute',
                top: 0,
                left: 0,
                width: '100%',
                transform: `translateY(${virtualRow.start}px)`,
              }}
            >
              {renderCardRow(flatRows[virtualRow.index])}
            </div>
          ))}
        </div>
      )}

      {/* Non-virtualized flat list */}
      {!showSubgroupHeadings && !shouldVirtualizeFlat && (
        <div className="grid grid-cols-2 gap-2">
          {filteredFiles.map((file) => (
            <ImportFileCard
              key={file.relative_path}
              file={file}
              jobId={jobId}
              existingSubgroups={groupSubgroups}
              selected={activeSelection.has(file.relative_path)}
              onToggleSelect={() => toggleFileSelection(activeGroupId, file.relative_path)}
              onUpdate={(updates) => onUpdateFile(file.relative_path, updates)}
              disabled={disabled}
            />
          ))}
        </div>
      )}

      {/* Virtualized subgroup list */}
      {shouldVirtualizeSubgroups && (
        <div
          style={{
            height: `${subgroupVirtualizer.getTotalSize()}px`,
            position: 'relative',
            width: '100%',
          }}
        >
          {subgroupVirtualizer.getVirtualItems().map((virtualItem) => {
            const item = subgroupItems[virtualItem.index]
            return (
              <div
                key={virtualItem.key}
                data-index={virtualItem.index}
                ref={subgroupVirtualizer.measureElement}
                style={{
                  position: 'absolute',
                  top: 0,
                  left: 0,
                  width: '100%',
                  transform: `translateY(${virtualItem.start}px)`,
                }}
              >
                {item.type === 'heading' ? (
                  <SubgroupHeading
                    subgroup={item.subgroup}
                    count={item.count}
                    isEditing={false}
                    existingSubgroups={groupSubgroups}
                    onStartEdit={() => {}}
                    onCommit={() => {}}
                    onCancel={() => {}}
                    onClear={() => {}}
                    canEdit={false}
                  />
                ) : (
                  renderCardRow(item.files)
                )}
              </div>
            )
          })}
        </div>
      )}

      {/* Non-virtualized subgroup list */}
      {showSubgroupHeadings &&
        !shouldVirtualizeSubgroups &&
        subgroupGroups.map((svGroup) => {
          const nonExcluded = svGroup.files.filter((f) => !f.excluded).length
          return (
            <div key={svGroup.subgroup ?? '__main__'} className="mb-2">
              <SubgroupHeading
                subgroup={svGroup.subgroup}
                count={nonExcluded}
                isEditing={false}
                existingSubgroups={groupSubgroups}
                onStartEdit={() => {}}
                onCommit={() => {}}
                onCancel={() => {}}
                onClear={() => {}}
                canEdit={false}
              />
              {renderCardRow(svGroup.files)}
            </div>
          )
        })}

      {/* Empty state messages */}
      {emptyFilterMessage && (
        <div className="flex flex-col items-center py-12 text-muted-foreground gap-2">
          <Search className="h-8 w-8 text-muted-foreground/20" />
          <p className="text-sm">No files match the current filter</p>
        </div>
      )}
      {emptyAllTabMessage && (
        <div className="flex flex-col items-center py-12 text-muted-foreground gap-2">
          <p className="text-sm">All groups are complete or skipped</p>
        </div>
      )}
    </div>
  )
}

export function ImportGroupContent({ s }: ImportGroupContentProps) {
  const {
    isAllTab,
    activeGroup,
    activeGroupId,
    sourceFiles,
    filteredFiles,
    pendingGroups,
    allSameAuthor,
    groups,
    activeTab,
    setGroups,
  } = s.files
  const {
    toggleFileSelection,
    selectAllVisible,
    deselectAll,
    activeSelection,
    updateGroup,
    updateFile,
    updateFileAnyGroup,
    moveToNewGroup,
  } = s.editing
  const { bulkSetImageType, bulkExclude, bulkSetDuplicateAction } = s.bulk
  const { fileFilter, setFileFilter } = s.filter
  const { subgroupGroups, showSubgroupHeadings, groupSubgroups } = s.subgroups
  const { authorSuggestions, duplicateCount, skippedDuplicateCount } = s.metadata
  const { handleConfirmGroup, handleConfirmAll, canImportActive, canImportAll } = s.confirm
  const { state, jobId } = s.workflow

  return (
    <div className="flex-1 min-w-0 flex flex-col overflow-hidden">
      {/* Group metadata */}
      <div className="px-5 pt-4 pb-3 border-b border-border/30 shrink-0">
        <MetadataForm
          author={isAllTab ? allSameAuthor : (activeGroup?.author ?? '')}
          groupName={isAllTab ? '' : (activeGroup?.group_name ?? '')}
          authorPlaceholder={
            isAllTab && !allSameAuthor ? 'Multiple — type to set for all groups' : 'Author name'
          }
          groupNamePlaceholder={isAllTab ? '— (varies by group)' : 'Group name'}
          authorDisabled={!isAllTab && activeGroup?.status !== 'pending'}
          groupNameDisabled={isAllTab || activeGroup?.status !== 'pending'}
          authorHighlight={
            !isAllTab && activeGroup?.author === '' && activeGroup?.status === 'pending'
          }
          authorSuggestions={authorSuggestions}
          suggestionsListId="author-suggestions"
          onAuthorChange={(val) => {
            if (isAllTab) {
              setGroups((prev) => prev.map((g) => ({ ...g, author: val })))
            } else {
              updateGroup(activeTab, { author: val })
            }
          }}
          onGroupNameChange={(val) => !isAllTab && updateGroup(activeTab, { group_name: val })}
        />
      </div>

      {/* Skip state placeholder */}
      {!isAllTab && activeGroup?.skip ? (
        <div className="flex-1 flex flex-col items-center justify-center text-muted-foreground gap-3">
          <SkipForward className="h-10 w-10 text-muted-foreground/20" />
          <p className="text-sm font-medium">Group skipped</p>
          <button
            onClick={() => updateGroup(activeTab, { skip: false })}
            className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-primary font-medium transition-colors"
          >
            <Undo2 className="h-3.5 w-3.5" />
            Undo
          </button>
        </div>
      ) : (
        <>
          {/* File toolbar */}
          {(isAllTab || activeGroup?.status === 'pending') && (
            <div className="px-5 shrink-0">
              <ImportFileToolbar
                files={sourceFiles}
                filteredFiles={filteredFiles}
                selection={activeSelection}
                filter={fileFilter}
                onFilterChange={setFileFilter}
                onSelectAll={() => selectAllVisible(activeGroupId, filteredFiles)}
                onDeselectAll={() => deselectAll(activeGroupId)}
                onBulkSetImageType={(v) => bulkSetImageType(isAllTab ? null : activeGroupId, v)}
                onBulkExclude={() => bulkExclude(isAllTab ? null : activeGroupId)}
                onMoveToNewGroup={
                  !isAllTab && activeGroup?.id ? () => moveToNewGroup(activeGroup.id) : undefined
                }
                duplicateCount={duplicateCount}
                skippedDuplicateCount={skippedDuplicateCount}
                onBulkSetDuplicateAction={(action) =>
                  bulkSetDuplicateAction(isAllTab ? null : activeGroupId, action)
                }
              />
            </div>
          )}

          {/* File gallery */}
          <FileGallery
            showSubgroupHeadings={showSubgroupHeadings}
            subgroupGroups={subgroupGroups}
            filteredFiles={filteredFiles}
            groupSubgroups={groupSubgroups}
            activeSelection={activeSelection}
            activeGroupId={activeGroupId}
            jobId={jobId!}
            disabled={!isAllTab && activeGroup?.status !== 'pending'}
            isAllTab={isAllTab}
            fileFilter={fileFilter}
            toggleFileSelection={toggleFileSelection}
            onUpdateFile={(relativePath, updates) =>
              isAllTab
                ? updateFileAnyGroup(relativePath, updates)
                : updateFile(activeTab, relativePath, updates)
            }
          />

          {/* Per-group status / footer */}
          {!isAllTab && activeGroup && (
            <div className="px-5 py-3 border-t border-border/30 shrink-0">
              {activeGroup.status === 'running' && (
                <div className="flex flex-col gap-2">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-1.5 text-sm text-muted-foreground">
                      <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />
                      Processing…
                    </div>
                    <span className="text-xs tabular-nums text-muted-foreground">
                      {activeGroup.processed} / {activeGroup.total}
                    </span>
                  </div>
                  <div className="w-full bg-secondary rounded-full h-1 overflow-hidden">
                    <div
                      className="bg-primary/70 h-full rounded-full transition-all duration-500 ease-out"
                      style={{
                        width: `${activeGroup.total > 0 ? Math.round((activeGroup.processed / activeGroup.total) * 100) : 0}%`,
                      }}
                    />
                  </div>
                </div>
              )}
              {activeGroup.status === 'completed' && (
                <div className="flex items-center gap-2 text-sm">
                  <Check className="h-4 w-4 text-primary" />
                  <span className="text-primary">{activeGroup.processed} images processed</span>
                  {activeGroup.failed > 0 && (
                    <span className="text-destructive">({activeGroup.failed} failed)</span>
                  )}
                </div>
              )}
              {activeGroup.status === 'failed' && (
                <div className="flex items-center gap-2 text-sm text-destructive">
                  <AlertCircle className="h-4 w-4" />
                  Import failed
                </div>
              )}
              {activeGroup.status === 'pending' && (
                <div className="flex items-center justify-between">
                  <span className="text-xs text-muted-foreground">
                    {activeGroup.files.filter((f) => !f.excluded).length} of{' '}
                    {activeGroup.files.length} files
                  </span>
                  <button
                    onClick={() => handleConfirmGroup(activeTab)}
                    disabled={!canImportActive}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm rounded border border-primary/40 bg-primary/20 text-primary hover:bg-primary/30 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    Import Group
                    <span className="opacity-60 text-xs">
                      ({activeGroup.files.filter((f) => !f.excluded).length})
                    </span>
                  </button>
                </div>
              )}
            </div>
          )}

          {/* All-tab footer */}
          {isAllTab && state === 'preview' && (
            <div className="px-5 py-3 border-t border-border/30 shrink-0 flex items-center justify-between">
              <span className="text-xs text-muted-foreground">
                {groups.reduce((s, g) => s + g.files.filter((f) => !f.excluded).length, 0)} files
                across {pendingGroups.length} pending groups
              </span>
              <button
                onClick={handleConfirmAll}
                disabled={!canImportAll}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm rounded border border-primary/40 bg-primary/20 text-primary hover:bg-primary/30 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              >
                Import All ({pendingGroups.length} groups)
              </button>
            </div>
          )}
        </>
      )}
    </div>
  )
}
