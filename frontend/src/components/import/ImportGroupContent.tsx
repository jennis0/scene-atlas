import {
  Check,
  AlertCircle,
  Loader2,
  SkipForward,
  Undo2,
  Search,
  Pencil,
  X,
} from 'lucide-react'
import { FileCard } from './FileCard'
import { FileToolbar } from './FileToolbar'
import type { UseImportStateReturn } from '@/hooks/useImportState'

type ImportState = UseImportStateReturn

interface ImportGroupContentProps {
  s: ImportState
}

export function ImportGroupContent({ s }: ImportGroupContentProps) {
  const {
    isAllTab, activeGroup, activeGroupId, sourceFiles, filteredFiles,
    activeSelection, groupSubgroups, showSubgroupHeadings, subgroupGroups,
    pendingGroups, allSameAuthor, canImportActive, canImportAll,
    tagVocab, fileFilter, jobId, groups, activeTab, state, authorSuggestions,
    editingSvHeading, svHeadingDraft,
    setFileFilter, setGroups, setEditingSvHeading, setSvHeadingDraft,
    updateGroup, updateFile, updateFileAnyGroup,
    selectAllVisible, deselectAll, toggleFileSelection,
    bulkAddTag, bulkSetGrid, bulkSetImageType, bulkSetSubgroup, bulkExclude, bulkSetDuplicateAction,
    duplicateCount, skippedDuplicateCount,
    moveToNewGroup,
    clearSubgroupLabel, renameSubgroup,
    handleConfirmGroup, handleConfirmAll,
  } = s

  return (
    <div className="flex-1 min-w-0 flex flex-col overflow-hidden">

      {/* Group metadata */}
      <div className="px-5 pt-4 pb-3 border-b border-border/30 shrink-0">
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-[10px] uppercase tracking-wider text-muted-foreground/60 mb-1.5 block font-semibold">
              Author
            </label>
            {/* Author datalist */}
            <datalist id="author-suggestions">
              {authorSuggestions.map((a) => <option key={a} value={a} />)}
            </datalist>
            <input
              value={isAllTab ? allSameAuthor : (activeGroup?.author ?? '')}
              onChange={(e) => {
                if (isAllTab) {
                  setGroups((prev) => prev.map((g) => ({ ...g, author: e.target.value })))
                } else {
                  updateGroup(activeTab, { author: e.target.value })
                }
              }}
              placeholder={isAllTab && !allSameAuthor ? 'Multiple — type to set for all groups' : 'Author name'}
              list="author-suggestions"
              disabled={!isAllTab && activeGroup?.status !== 'pending'}
              className={`w-full h-8 px-3 text-sm rounded border bg-secondary text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/40 transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${
                !isAllTab && activeGroup?.author === '' && activeGroup?.status === 'pending'
                  ? 'border-primary/50'
                  : 'border-border'
              }`}
            />
          </div>
          <div>
            <label className="text-[10px] uppercase tracking-wider text-muted-foreground/60 mb-1.5 block font-semibold">
              Group Name
            </label>
            <input
              value={isAllTab ? '' : (activeGroup?.group_name ?? '')}
              onChange={(e) => !isAllTab && updateGroup(activeTab, { group_name: e.target.value })}
              placeholder={isAllTab ? '— (varies by group)' : 'Group name'}
              disabled={isAllTab || (activeGroup?.status !== 'pending')}
              className="w-full h-8 px-3 text-sm rounded border border-border bg-secondary text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/40 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            />
          </div>
        </div>
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
            <Undo2 className="h-3.5 w-3.5" />Undo
          </button>
        </div>
      ) : (
        <>
          {/* File toolbar */}
          {(isAllTab || activeGroup?.status === 'pending') && (
            <div className="px-5">
              <FileToolbar
                files={sourceFiles}
                filteredFiles={filteredFiles}
                selection={activeSelection}
                filter={fileFilter}
                vocab={tagVocab}
                onFilterChange={setFileFilter}
                onSelectAll={() => selectAllVisible(activeGroupId, filteredFiles)}
                onDeselectAll={() => deselectAll(activeGroupId)}
                onBulkAddTag={(tag) => bulkAddTag(isAllTab ? null : activeGroupId, tag)}
                onBulkSetGrid={(v) => bulkSetGrid(isAllTab ? null : activeGroupId, v)}
                onBulkSetImageType={(v) => bulkSetImageType(isAllTab ? null : activeGroupId, v)}
                onBulkSetSubgroup={(v) => bulkSetSubgroup(isAllTab ? null : activeGroupId, v)}
                onBulkExclude={() => bulkExclude(isAllTab ? null : activeGroupId)}
                onMoveToNewGroup={!isAllTab && activeGroup?.id ? () => moveToNewGroup(activeGroup.id) : undefined}
                duplicateCount={duplicateCount}
                skippedDuplicateCount={skippedDuplicateCount}
                onBulkSetDuplicateAction={(action) => bulkSetDuplicateAction(isAllTab ? null : activeGroupId, action)}
                alwaysShowTypeToggle
              />
            </div>
          )}

          {/* File gallery */}
          <div className="min-h-0 flex-1 overflow-y-auto px-5 py-3">
            {showSubgroupHeadings ? (
              subgroupGroups.map((svGroup) => {
                const nonExcluded = svGroup.files.filter((f) => !f.excluded).length
                const groupOwner = !isAllTab ? activeGroup : null
                const isEditing = !isAllTab && editingSvHeading === svGroup.subgroup && svGroup.subgroup !== null
                return (
                  <div key={svGroup.subgroup ?? '__main__'} className="mb-2">
                    <div className="flex items-center gap-2 py-1.5 mt-2 first:mt-0">
                      {isEditing ? (
                        <input
                          value={svHeadingDraft}
                          autoFocus
                          onChange={(e) => setSvHeadingDraft(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') { renameSubgroup(activeGroup!.id, svGroup.subgroup!, svHeadingDraft); setEditingSvHeading(null) }
                            if (e.key === 'Escape') setEditingSvHeading(null)
                          }}
                          onBlur={() => { renameSubgroup(activeGroup!.id, svGroup.subgroup!, svHeadingDraft); setEditingSvHeading(null) }}
                          className="text-[11px] font-semibold text-foreground border-b border-primary/70 bg-transparent outline-none uppercase tracking-wider capitalize"
                        />
                      ) : (
                        <span className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider capitalize whitespace-nowrap">
                          {svGroup.subgroup ?? 'Main'}
                        </span>
                      )}
                      {groupOwner?.status === 'pending' && svGroup.subgroup !== null && !isEditing && (
                        <button
                          onClick={() => { setSvHeadingDraft(svGroup.subgroup!); setEditingSvHeading(svGroup.subgroup!) }}
                          className="text-muted-foreground/40 hover:text-muted-foreground transition-colors"
                        >
                          <Pencil className="h-3 w-3" />
                        </button>
                      )}
                      <div className="flex-1 h-px bg-border/30" />
                      <span className="text-[11px] text-muted-foreground/40 tabular-nums">{nonExcluded}</span>
                      {groupOwner?.status === 'pending' && svGroup.subgroup !== null && !isEditing && (
                        <button
                          onClick={() => clearSubgroupLabel(activeGroup!.id, svGroup.subgroup!)}
                          className="text-muted-foreground/40 hover:text-primary transition-colors"
                        >
                          <X className="h-3.5 w-3.5" />
                        </button>
                      )}
                    </div>
                    <div className="space-y-1.5 pb-2">
                      {svGroup.files.map((file) => (
                        <FileCard
                          key={file.relative_path}
                          file={file}
                          jobId={jobId!}
                          vocab={tagVocab}
                          existingSubgroups={groupSubgroups}
                          selected={activeSelection.has(file.relative_path)}
                          onToggleSelect={() => toggleFileSelection(activeGroupId, file.relative_path)}
                          onUpdate={(updates) =>
                            isAllTab
                              ? updateFileAnyGroup(file.relative_path, updates)
                              : updateFile(activeTab, file.relative_path, updates)
                          }
                          disabled={!isAllTab && activeGroup?.status !== 'pending'}
                        />
                      ))}
                    </div>
                  </div>
                )
              })
            ) : (
              <div className="space-y-1.5">
                {filteredFiles.map((file) => (
                  <FileCard
                    key={file.relative_path}
                    file={file}
                    jobId={jobId!}
                    vocab={tagVocab}
                    existingSubgroups={groupSubgroups}
                    selected={activeSelection.has(file.relative_path)}
                    onToggleSelect={() => toggleFileSelection(activeGroupId, file.relative_path)}
                    onUpdate={(updates) =>
                      isAllTab
                        ? updateFileAnyGroup(file.relative_path, updates)
                        : updateFile(activeTab, file.relative_path, updates)
                    }
                    disabled={!isAllTab && activeGroup?.status !== 'pending'}
                  />
                ))}
              </div>
            )}
            {filteredFiles.length === 0 && (fileFilter.text || fileFilter.active.length > 0) && (
              <div className="flex flex-col items-center py-12 text-muted-foreground gap-2">
                <Search className="h-8 w-8 text-muted-foreground/20" />
                <p className="text-sm">No files match the current filter</p>
              </div>
            )}
            {filteredFiles.length === 0 && !fileFilter.text && fileFilter.active.length === 0 && isAllTab && (
              <div className="flex flex-col items-center py-12 text-muted-foreground gap-2">
                <p className="text-sm">All groups are complete or skipped</p>
              </div>
            )}
          </div>

          {/* Per-group status / footer */}
          {!isAllTab && activeGroup && (
            <div className="px-5 py-3 border-t border-border/30 shrink-0">
              {activeGroup.status === 'running' && (
                <div className="flex flex-col gap-2">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-1.5 text-sm text-muted-foreground">
                      <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />Processing…
                    </div>
                    <span className="text-xs tabular-nums text-muted-foreground">
                      {activeGroup.processed} / {activeGroup.total}
                    </span>
                  </div>
                  <div className="w-full bg-secondary rounded-full h-1 overflow-hidden">
                    <div
                      className="bg-primary/70 h-full rounded-full transition-all duration-500 ease-out"
                      style={{ width: `${activeGroup.total > 0 ? Math.round((activeGroup.processed / activeGroup.total) * 100) : 0}%` }}
                    />
                  </div>
                </div>
              )}
              {activeGroup.status === 'completed' && (
                <div className="flex items-center gap-2 text-sm">
                  <Check className="h-4 w-4 text-primary" />
                  <span className="text-primary">{activeGroup.processed} images processed</span>
                  {activeGroup.failed > 0 && <span className="text-destructive">({activeGroup.failed} failed)</span>}
                </div>
              )}
              {activeGroup.status === 'failed' && (
                <div className="flex items-center gap-2 text-sm text-destructive">
                  <AlertCircle className="h-4 w-4" />Import failed
                </div>
              )}
              {activeGroup.status === 'pending' && (
                <div className="flex items-center justify-between">
                  <span className="text-xs text-muted-foreground">
                    {activeGroup.files.filter((f) => !f.excluded).length} of {activeGroup.files.length} files
                  </span>
                  <button
                    onClick={() => handleConfirmGroup(activeTab)}
                    disabled={!canImportActive}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm rounded border border-primary/40 bg-primary/20 text-primary hover:bg-primary/30 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    Import Group
                    <span className="opacity-60 text-xs">({activeGroup.files.filter((f) => !f.excluded).length})</span>
                  </button>
                </div>
              )}
            </div>
          )}

          {/* All-tab footer */}
          {isAllTab && state === 'preview' && (
            <div className="px-5 py-3 border-t border-border/30 shrink-0 flex items-center justify-between">
              <span className="text-xs text-muted-foreground">
                {groups.reduce((s, g) => s + g.files.filter((f) => !f.excluded).length, 0)} files across {pendingGroups.length} pending groups
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
