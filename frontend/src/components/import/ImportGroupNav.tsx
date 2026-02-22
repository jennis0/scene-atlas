import { Check, Loader2, AlertCircle, MoreHorizontal, SkipForward, Merge } from 'lucide-react'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { ALL_TAB } from '@/hooks/useImportState'
import type { DialogState } from '@/hooks/useImportState'
import type { EditableGroupState } from '@/types'

interface ImportGroupNavProps {
  groups: EditableGroupState[]
  activeTab: number
  state: DialogState
  totalFiles: number
  pendingGroupCount: number
  canImportAll: boolean
  onSelectTab: (tab: number) => void
  onUpdateGroup: (index: number, updates: Partial<EditableGroupState>) => void
  onMergeGroups: (sourceIndex: number, targetIndex: number) => void
  onConfirmAll: () => void
}

export function ImportGroupNav({
  groups,
  activeTab,
  state,
  totalFiles,
  pendingGroupCount,
  canImportAll,
  onSelectTab,
  onUpdateGroup,
  onMergeGroups,
  onConfirmAll,
}: ImportGroupNavProps) {
  const isAllTab = activeTab === ALL_TAB

  return (
    <div className="w-[190px] shrink-0 border-r border-border/30 flex flex-col overflow-hidden bg-muted/20">
      <div className="px-3 py-2.5 border-b border-border/30 shrink-0">
        <span className="text-[10px] uppercase tracking-wider text-muted-foreground/60 font-semibold">
          {groups.length} groups · {totalFiles} files
        </span>
      </div>

      {/* Scrollable group list */}
      <div className="flex-1 overflow-y-auto py-1">
        {/* "All" entry */}
        <button
          onClick={() => onSelectTab(ALL_TAB)}
          className={`w-full flex items-center gap-2 px-3 py-2 text-left transition-colors border-l-2 ${
            isAllTab
              ? 'border-primary bg-primary/10 text-primary'
              : 'border-transparent text-muted-foreground hover:text-foreground hover:bg-secondary/50'
          }`}
        >
          <span className="font-display text-[13px] font-semibold flex-1">All</span>
          <span className="text-[11px] text-muted-foreground/40 tabular-nums shrink-0">
            {groups.reduce((s, g) => s + g.files.filter((f) => !f.excluded).length, 0)}
          </span>
        </button>
        <div className="h-px bg-border/30 mx-3 my-0.5" />

        {groups.map((g, i) => (
          <div key={g.id} className="flex items-center group/nav">
            <button
              onClick={() => onSelectTab(i)}
              className={`flex-1 flex items-center gap-2 px-3 py-2 text-left transition-colors border-l-2 min-w-0 ${
                activeTab === i
                  ? 'border-primary bg-primary/10 text-primary'
                  : 'border-transparent text-muted-foreground hover:text-foreground hover:bg-secondary/50'
              } ${g.skip ? 'opacity-40' : ''}`}
            >
              <span className="shrink-0 w-3 flex justify-center">
                {g.status === 'completed' && <Check className="h-3 w-3" />}
                {g.status === 'running' && <Loader2 className="h-3 w-3 animate-spin" />}
                {g.status === 'failed' && <AlertCircle className="h-3 w-3 text-destructive" />}
                {g.status === 'pending' && !g.skip && (
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
            {g.status === 'pending' && (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <button className="opacity-0 group-hover/nav:opacity-100 p-1.5 text-muted-foreground/40 hover:text-muted-foreground transition-all shrink-0">
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
                      <DropdownMenuLabel className="text-xs text-muted-foreground">
                        Merge into…
                      </DropdownMenuLabel>
                      {groups.map((target, j) =>
                        j !== i ? (
                          <DropdownMenuItem key={target.id} onClick={() => onMergeGroups(i, j)}>
                            <Merge className="h-4 w-4 mr-2" />
                            {target.group_name}
                          </DropdownMenuItem>
                        ) : null,
                      )}
                    </>
                  )}
                </DropdownMenuContent>
              </DropdownMenu>
            )}
          </div>
        ))}
      </div>

      {/* Import All button at bottom of sidebar */}
      {pendingGroupCount > 1 && state === 'preview' && (
        <div className="p-2.5 border-t border-border/30 shrink-0">
          <button
            onClick={onConfirmAll}
            disabled={!canImportAll}
            className="w-full text-[12px] py-1.5 rounded border border-primary/40 bg-primary/10 text-primary hover:bg-primary/20 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            Import All ({pendingGroupCount})
          </button>
        </div>
      )}
    </div>
  )
}
