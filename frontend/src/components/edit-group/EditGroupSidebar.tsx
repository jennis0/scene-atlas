import { Check, EyeOff, Loader2, Merge, MoreHorizontal, Trash2 } from 'lucide-react'
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
} from '@/components/ui/dropdown-menu'
import { GroupSidebarShell } from '@/components/import/shared/GroupSidebarShell'
import { DroppableGroupRow, DraggableGroupRow } from '@/components/import/shared/dnd'
import type { EditableGroupState } from '@/types'
import { useEditGroupContext } from './EditGroupContext'

type GroupClickHandler = (index: number, groupId: string, e: React.MouseEvent) => void

interface EditGroupSidebarProps {
  activeTab: number
  isAllTab: boolean
  onSelectAll: () => void
  onGroupClick: GroupClickHandler
  totalInScope: number
  /** Mass edit and import review get per-group menus and merge/delete actions. */
  hasGroupActions: boolean
}

const FOOTER_BUTTON =
  'text-[11px] py-1 rounded border transition-colors flex items-center justify-center gap-1 disabled:opacity-40'

export function EditGroupSidebar({
  activeTab,
  isAllTab,
  onSelectAll,
  onGroupClick,
  totalInScope,
  hasGroupActions,
}: EditGroupSidebarProps) {
  const { groups, activeDrag } = useEditGroupContext()

  return (
    <GroupSidebarShell
      headerLabel={`${groups.length} groups`}
      allCount={totalInScope}
      isAllActive={isAllTab}
      onSelectAll={onSelectAll}
      footer={hasGroupActions ? <SidebarFooter /> : undefined}
    >
      {groups.map((g, i) => (
        <DroppableGroupRow key={g.id} groupId={g.id} activeDrag={activeDrag}>
          <DraggableGroupRow groupId={g.id} isDndEnabled>
            <div className="group/navrow">
              <GroupRow
                group={g}
                index={i}
                isActive={activeTab === i}
                hasGroupActions={hasGroupActions}
                onClick={onGroupClick}
              />
            </div>
          </DraggableGroupRow>
        </DroppableGroupRow>
      ))}
    </GroupSidebarShell>
  )
}

/** Merge/delete for the multi-selection, or Merge All when nothing is multi-selected. */
function SidebarFooter() {
  const { selectedGroupIds, setPending, ops } = useEditGroupContext()
  const disabled = ops.merging || ops.saving

  return (
    <div className="p-2.5 border-t border-border/30 shrink-0">
      {selectedGroupIds.size >= 2 ? (
        <div className="space-y-1.5">
          <span className="text-xs text-muted-foreground font-semibold">
            {selectedGroupIds.size} selected
          </span>
          <div className="flex gap-1">
            <button
              onClick={() => setPending({ kind: 'bulkMerge' })}
              disabled={disabled}
              className={`flex-1 ${FOOTER_BUTTON} border-border/40 bg-secondary/30 text-muted-foreground hover:bg-secondary/60 hover:text-foreground`}
            >
              <Merge className="h-3 w-3" />
              Merge
            </button>
            <button
              onClick={() => setPending({ kind: 'bulkDelete' })}
              disabled={disabled}
              className={`flex-1 ${FOOTER_BUTTON} border-destructive/30 bg-destructive/5 text-destructive/70 hover:bg-destructive/10 hover:text-destructive`}
            >
              <Trash2 className="h-3 w-3" />
              Delete
            </button>
          </div>
        </div>
      ) : (
        <button
          onClick={() => setPending({ kind: 'mergeAll' })}
          disabled={disabled}
          className="w-full text-[12px] py-1.5 rounded border border-border/40 bg-secondary/30 text-muted-foreground hover:bg-secondary/60 hover:text-foreground transition-colors flex items-center justify-center gap-1.5 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <Merge className="h-3.5 w-3.5" />
          {ops.merging ? 'Merging…' : 'Merge All'}
        </button>
      )}
    </div>
  )
}

interface GroupRowProps {
  group: EditableGroupState
  index: number
  isActive: boolean
  hasGroupActions: boolean
  onClick: GroupClickHandler
}

function GroupRow({ group, index, isActive, hasGroupActions, onClick }: GroupRowProps) {
  const { selectedGroupIds, pending, setPending, ops } = useEditGroupContext()

  if (pending?.kind === 'deleteRow' && pending.groupId === group.id) {
    return (
      <RowDeleteConfirm
        saving={ops.saving}
        onConfirm={async () => {
          if (await ops.handleDeleteGroup(group.id)) setPending(null)
        }}
        onCancel={() => setPending(null)}
      />
    )
  }

  const rowState = selectedGroupIds.has(group.id)
    ? 'border-primary/60 bg-primary/15 text-primary'
    : isActive
      ? 'border-primary bg-primary/10 text-primary'
      : 'border-transparent text-muted-foreground hover:text-foreground hover:bg-secondary/50'

  return (
    <div className={`flex items-center transition-colors border-l-2 ${rowState}`}>
      <button
        onClick={(e) => onClick(index, group.id, e)}
        className="flex-1 flex items-center gap-2 pl-3 pr-1 py-2 text-left min-w-0"
      >
        <span className="flex-1 text-[12px] truncate">{group.group_name}</span>
        <GroupRowCounts group={group} />
      </button>
      {hasGroupActions && <GroupRowMenu groupId={group.id} />}
    </div>
  )
}

/** In-scope image count, out-of-scope extras, and the auto-save indicator. */
function GroupRowCounts({ group }: { group: EditableGroupState }) {
  const { ops } = useEditGroupContext()
  const outOfScope = group.files.filter((f) => f.outOfScope).length

  return (
    <span className="text-[11px] text-muted-foreground tabular-nums shrink-0 flex items-center gap-1">
      {group.files.filter((f) => !f.excluded && !f.outOfScope).length}
      {outOfScope > 0 && <span className="ml-0.5 opacity-80">+{outOfScope}</span>}
      {ops.groupSaving.has(group.id) ? (
        <Loader2 className="h-3 w-3 animate-spin text-muted-foreground ml-1" />
      ) : ops.groupSaved.has(group.id) ? (
        <Check className="h-3 w-3 text-emerald-600 dark:text-emerald-400/70 ml-1" />
      ) : null}
    </span>
  )
}

function GroupRowMenu({ groupId }: { groupId: string }) {
  const { setPending, ops } = useEditGroupContext()

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          className="opacity-0 focus-visible:opacity-100 [@media(hover:none)]:opacity-100 group-hover/navrow:opacity-100 h-7 w-6 mr-1 flex items-center justify-center rounded text-muted-foreground hover:text-foreground hover:bg-black/5 dark:hover:bg-white/5 transition-all shrink-0"
          onClick={(e) => e.stopPropagation()}
        >
          <MoreHorizontal className="h-3.5 w-3.5" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" onCloseAutoFocus={(e) => e.preventDefault()}>
        <DropdownMenuItem onClick={() => setPending({ kind: 'mergeInto', sourceId: groupId })}>
          <Merge className="h-4 w-4 mr-2" />
          Merge into…
        </DropdownMenuItem>
        <DropdownMenuItem onClick={() => ops.removeGroupFromView(groupId)}>
          <EyeOff className="h-4 w-4 mr-2" />
          Remove from view
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          onClick={() => setPending({ kind: 'deleteRow', groupId })}
          className="text-destructive focus:text-destructive"
        >
          <Trash2 className="h-4 w-4 mr-2" />
          Delete group
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

function RowDeleteConfirm({
  saving,
  onConfirm,
  onCancel,
}: {
  saving: boolean
  onConfirm: () => void
  onCancel: () => void
}) {
  const button = 'px-2 py-0.5 rounded border text-[10px] transition-colors disabled:opacity-50'
  return (
    <div className="px-3 py-2 border-l-2 border-destructive/50 bg-destructive/5">
      <p className="text-[11px] text-destructive/80 mb-1.5">Delete this group?</p>
      <div className="flex gap-1">
        <button
          onClick={onConfirm}
          disabled={saving}
          className={`${button} border-destructive/50 bg-destructive/10 text-destructive hover:bg-destructive/20`}
        >
          {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : 'Delete'}
        </button>
        <button
          onClick={onCancel}
          disabled={saving}
          className={`${button} border-border bg-secondary text-muted-foreground hover:text-foreground`}
        >
          Cancel
        </button>
      </div>
    </div>
  )
}
