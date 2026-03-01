import { useState } from 'react'
import { Check, Loader2, AlertCircle, MoreHorizontal, SkipForward, Merge } from 'lucide-react'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { ImportMergeGroupPicker } from './ImportMergeGroupPicker'
import { DraggableGroupRow, DroppableGroupRow } from './shared/dnd'
import type { ActiveDragState } from './shared/dnd'
import { ALL_TAB } from '@/hooks/useImportState'
import { GroupSidebarShell } from './shared/GroupSidebarShell'
import type { DialogState } from '@/hooks/useImportState'
import type { EditableGroupState } from '@/types'

interface ImportGroupNavProps {
  groups: EditableGroupState[]
  activeTab: number
  state: DialogState
  totalFiles: number
  pendingGroupCount: number
  canImportAll: boolean
  canMergeAll: boolean
  activeDrag?: ActiveDragState | null
  onSelectTab: (tab: number) => void
  onUpdateGroup: (index: number, updates: Partial<EditableGroupState>) => void
  onMergeGroups: (sourceIndex: number, targetIndex: number) => void
  onMergeAllGroups: () => void
  onConfirmAll: () => void
}

export function ImportGroupNav({
  groups,
  activeTab,
  state,
  totalFiles,
  pendingGroupCount,
  canImportAll,
  canMergeAll,
  activeDrag,
  onSelectTab,
  onUpdateGroup,
  onMergeGroups,
  onMergeAllGroups,
  onConfirmAll,
}: ImportGroupNavProps) {
  const isAllTab = activeTab === ALL_TAB
  const [confirmingMergeAll, setConfirmingMergeAll] = useState(false)
  const [mergeSourceIndex, setMergeSourceIndex] = useState<number | null>(null)

  // Split groups into active (pending) and submitted (non-pending), preserving original indices
  const activeGroups: { group: EditableGroupState; index: number }[] = []
  const submittedGroups: { group: EditableGroupState; index: number }[] = []
  groups.forEach((g, i) => {
    if (g.status === 'pending') {
      activeGroups.push({ group: g, index: i })
    } else {
      submittedGroups.push({ group: g, index: i })
    }
  })

  return (
    <>
      <GroupSidebarShell
        headerLabel={`${groups.length} groups · ${totalFiles} files`}
        allCount={groups.reduce((s, g) => s + g.files.filter((f) => !f.excluded).length, 0)}
        isAllActive={isAllTab}
        onSelectAll={() => onSelectTab(ALL_TAB)}
        footer={
          state === 'preview' && (canMergeAll || pendingGroupCount > 1) ? (
            <div className="p-2.5 border-t border-border/30 shrink-0 space-y-1.5">
              {canMergeAll && (
                <button
                  onClick={() => setConfirmingMergeAll(true)}
                  className="w-full text-[12px] py-1.5 rounded border border-border/40 bg-secondary/30 text-muted-foreground hover:bg-secondary/60 hover:text-foreground transition-colors flex items-center justify-center gap-1.5"
                >
                  <Merge className="h-3.5 w-3.5" />
                  Merge All
                </button>
              )}
              {pendingGroupCount > 1 && (
                <button
                  onClick={onConfirmAll}
                  disabled={!canImportAll}
                  className="w-full text-[12px] py-1.5 rounded border border-primary/40 bg-primary/10 text-primary hover:bg-primary/20 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  Import All ({pendingGroupCount})
                </button>
              )}
            </div>
          ) : undefined
        }
      >
        {/* Active (pending) groups */}
        {activeGroups.map(({ group: g, index: i }) => (
          <DroppableGroupRow key={g.id} groupId={g.id} activeDrag={activeDrag ?? null}>
            <DraggableGroupRow groupId={g.id} isDndEnabled={state === 'preview' && !g.skip}>
              <div
                className={`flex items-center group/nav transition-colors border-l-2 ${
                  activeTab === i
                    ? 'border-primary bg-primary/10 text-primary'
                    : 'border-transparent text-muted-foreground hover:text-foreground hover:bg-secondary/50'
                } ${g.skip ? 'opacity-40' : ''}`}
              >
                <button
                  onClick={() => onSelectTab(i)}
                  className="flex-1 flex items-center gap-2 px-3 py-2 text-left min-w-0"
                >
                  <span className="shrink-0 w-3 flex justify-center">
                    {!g.skip && (
                      <span className="h-1.5 w-1.5 rounded-full bg-current opacity-50 inline-block" />
                    )}
                    {g.skip && <SkipForward className="h-3 w-3" />}
                  </span>
                  <span className={`flex-1 text-[12px] truncate ${g.skip ? 'line-through' : ''}`}>
                    {g.group_name}
                  </span>
                  <span className="text-[11px] text-muted-foreground/40 tabular-nums shrink-0">
                    {g.files.filter((f) => !f.excluded).length}
                  </span>
                </button>
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <button className="opacity-0 group-hover/nav:opacity-100 focus:opacity-100 p-1.5 mr-1 text-muted-foreground/40 hover:text-muted-foreground transition-all shrink-0 rounded hover:bg-black/5 dark:hover:bg-white/5">
                      <MoreHorizontal className="h-3.5 w-3.5" />
                    </button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end" side="right">
                    <DropdownMenuItem onClick={() => onUpdateGroup(i, { skip: !g.skip })}>
                      <SkipForward className="h-4 w-4 mr-2" />
                      {g.skip ? 'Unskip Group' : 'Skip Group'}
                    </DropdownMenuItem>
                    {groups.length > 1 && (
                      <>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem onClick={() => setMergeSourceIndex(i)}>
                          <Merge className="h-4 w-4 mr-2" />
                          Merge into…
                        </DropdownMenuItem>
                      </>
                    )}
                  </DropdownMenuContent>
                </DropdownMenu>
              </div>
            </DraggableGroupRow>
          </DroppableGroupRow>
        ))}

        {/* Divider between active and submitted */}
        {activeGroups.length > 0 && submittedGroups.length > 0 && (
          <div className="mx-3 my-1.5 flex items-center gap-2">
            <div className="flex-1 h-px bg-border/30" />
            <span className="text-[9px] uppercase tracking-wider text-muted-foreground/40 font-medium shrink-0">
              Submitted
            </span>
            <div className="flex-1 h-px bg-border/30" />
          </div>
        )}

        {/* Submitted (non-pending) groups — de-emphasized */}
        {submittedGroups.map(({ group: g, index: i }) => (
          <DroppableGroupRow key={g.id} groupId={g.id} activeDrag={activeDrag ?? null}>
            <div className="flex items-center">
              <button
                onClick={() => onSelectTab(i)}
                className={`flex-1 flex items-center gap-2 px-3 py-1.5 text-left transition-colors border-l-2 min-w-0 opacity-50 ${
                  activeTab === i
                    ? 'border-primary/50 bg-primary/5 text-primary/70'
                    : 'border-transparent text-muted-foreground/60 hover:text-muted-foreground hover:bg-secondary/20'
                }`}
              >
                <span className="shrink-0 w-3 flex justify-center">
                  {g.status === 'completed' && <Check className="h-3 w-3" />}
                  {g.status === 'running' && <Loader2 className="h-3 w-3 animate-spin" />}
                  {g.status === 'failed' && <AlertCircle className="h-3 w-3 text-destructive" />}
                </span>
                <span className="flex-1 text-[12px] truncate">{g.group_name}</span>
                <span className="text-[11px] text-muted-foreground/30 tabular-nums shrink-0">
                  {g.files.filter((f) => !f.excluded).length}
                </span>
              </button>
            </div>
          </DroppableGroupRow>
        ))}
      </GroupSidebarShell>

      <ImportMergeGroupPicker
        open={mergeSourceIndex !== null}
        onClose={() => setMergeSourceIndex(null)}
        groups={groups}
        sourceIndex={mergeSourceIndex ?? 0}
        onSelect={(targetIndex) => {
          if (mergeSourceIndex !== null) {
            onMergeGroups(mergeSourceIndex, targetIndex)
            setMergeSourceIndex(null)
          }
        }}
        currentGroupName={mergeSourceIndex !== null ? groups[mergeSourceIndex]?.group_name : ''}
      />

      <ConfirmDialog
        open={confirmingMergeAll}
        onOpenChange={setConfirmingMergeAll}
        title="Merge All Groups"
        description={`This will merge ${pendingGroupCount} pending groups into one. The first group's name and author will be kept.`}
        confirmLabel="Merge"
        confirmVariant="default"
        onConfirm={() => {
          setConfirmingMergeAll(false)
          onMergeAllGroups()
        }}
      />
    </>
  )
}
