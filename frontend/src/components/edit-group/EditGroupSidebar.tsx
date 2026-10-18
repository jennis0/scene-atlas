import { useMemo, useState } from 'react'
import { Check, EyeOff, Loader2, Merge, MoreHorizontal, Trash2 } from 'lucide-react'
import { TypeCounts } from '@/components/imports/TypeCounts'
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
} from '@/components/ui/dropdown-menu'
import { GroupSidebarShell, type AllTab } from '@/components/import/shared/GroupSidebarShell'
import { DroppableGroupRow, DraggableGroupRow } from '@/components/import/shared/dnd'
import { serverId } from '@/lib/serverId'
import type { EditableGroupState, GroupSummary } from '@/types'
import { useEditGroupContext } from './EditGroupContext'
import { SidebarList } from './SidebarList'
import { sidebarRows, type LoadedSidebarRow, type SidebarRow } from './sidebarRows'

type GroupClickHandler = (index: number, groupId: string, e: React.MouseEvent) => void

interface EditGroupSidebarProps {
  activeTab: number
  allTab: AllTab
  onGroupClick: GroupClickHandler
  /** Mass edit and import review get per-group menus and merge/delete actions. */
  hasGroupActions: boolean
  /** Import review: groups listed from their summaries whose files are still loading */
  pending?: PendingGroups
  /** Import review: group ids in sidebar order (see sidebarRows) */
  order?: number[]
}

interface PendingGroups {
  groups: GroupSummary[]
  /** The one the user clicked: it loads next, then opens */
  awaitedId: number | null
  onOpen: (groupId: number) => void
  /** Large import review: groups load only when opened, so pending isn't "still loading" */
  onDemand?: boolean
}

const FOOTER_BUTTON =
  'text-2xs py-1 rounded border transition-colors flex items-center justify-center gap-1 disabled:opacity-40'

const NO_PENDING: PendingGroups = { groups: [], awaitedId: null, onOpen: () => {} }

/** "12 of 68 groups" while groups are still loading, else "68 groups". */
function headerLabel(loaded: number, pending: PendingGroups) {
  const total = (loaded + pending.groups.length).toLocaleString()
  if (pending.groups.length === 0 || pending.onDemand) return `${total} groups`
  return `${loaded.toLocaleString()} of ${total} groups`
}

export function EditGroupSidebar({
  activeTab,
  allTab,
  onGroupClick,
  hasGroupActions,
  pending = NO_PENDING,
  order = [],
}: EditGroupSidebarProps) {
  const { groups } = useEditGroupContext()
  const [query, setQuery] = useState('')
  // State, not a ref: the list's virtualiser needs it on its first layout effect
  const [scrollElement, setScrollElement] = useState<HTMLDivElement | null>(null)
  const total = groups.length + pending.groups.length
  const rows = useMemo(
    () => sidebarRows(groups, pending.groups, order, query),
    [groups, pending.groups, order, query],
  )
  const activeIndex = allTab.active ? null : activeTab

  return (
    <GroupSidebarShell
      headerLabel={headerLabel(groups.length, pending)}
      allTab={allTab}
      footer={hasGroupActions ? <SidebarFooter canMergeAll={!pending.onDemand} /> : undefined}
      toolbar={total >= FILTER_FROM ? <GroupNameFilter value={query} onChange={setQuery} /> : null}
      scrollRef={setScrollElement}
    >
      <SidebarList
        rows={rows}
        scrollElement={scrollElement}
        render={(row) => (
          <SidebarRowView
            row={row}
            pending={pending}
            activeIndex={activeIndex}
            hasGroupActions={hasGroupActions}
            onGroupClick={onGroupClick}
          />
        )}
      />
    </GroupSidebarShell>
  )
}

interface SidebarRowViewProps {
  row: SidebarRow
  pending: PendingGroups
  activeIndex: number | null
  hasGroupActions: boolean
  onGroupClick: GroupClickHandler
}

function SidebarRowView({
  row,
  pending,
  activeIndex,
  hasGroupActions,
  onGroupClick,
}: SidebarRowViewProps) {
  if (row.kind === 'pending') {
    return (
      <PendingGroupRow
        group={row.summary}
        awaited={pending.awaitedId === row.summary.id}
        onOpen={pending.onOpen}
        onDemand={pending.onDemand ?? false}
      />
    )
  }
  return (
    <LoadedGroupRow
      row={row}
      isActive={activeIndex === row.index}
      hasGroupActions={hasGroupActions}
      onClick={onGroupClick}
    />
  )
}

/** From this many groups, the sidebar offers a filter by name. */
const FILTER_FROM = 30

interface GroupNameFilterProps {
  value: string
  onChange: (v: string) => void
}

function GroupNameFilter({ value, onChange }: GroupNameFilterProps) {
  return (
    <div className="px-2 py-1.5 border-b border-border/30 shrink-0">
      <input
        type="search"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="Filter groups…"
        aria-label="Filter groups by name"
        className="w-full h-7 px-2 text-xs rounded border border-border bg-background text-foreground placeholder:text-muted-foreground"
      />
    </div>
  )
}

interface LoadedGroupRowProps {
  row: LoadedSidebarRow
  isActive: boolean
  hasGroupActions: boolean
  onClick: GroupClickHandler
}

function LoadedGroupRow({ row, isActive, hasGroupActions, onClick }: LoadedGroupRowProps) {
  const { activeDrag } = useEditGroupContext()
  return (
    <DroppableGroupRow groupId={row.group.id} activeDrag={activeDrag}>
      <DraggableGroupRow groupId={row.group.id} isDndEnabled>
        <div className="group/navrow">
          <GroupRow
            group={row.group}
            index={row.index}
            isActive={isActive}
            hasGroupActions={hasGroupActions}
            onClick={onClick}
          />
        </div>
      </DraggableGroupRow>
    </DroppableGroupRow>
  )
}

/**
 * Merge/delete for the multi-selection, or Merge All when nothing is multi-selected.
 * Not in large import review: Merge All only sees the groups opened so far.
 */
interface SidebarFooterProps {
  canMergeAll: boolean
}

function SidebarFooter({ canMergeAll }: SidebarFooterProps) {
  const { selectedGroupIds, setPending, ops } = useEditGroupContext()
  const disabled = ops.merging || ops.saving
  const multiSelected = selectedGroupIds.size >= 2
  if (!multiSelected && !canMergeAll) return null

  return (
    <div className="p-2.5 border-t border-border/30 shrink-0">
      {multiSelected ? (
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
          className="w-full text-xs py-1.5 rounded border border-border/40 bg-secondary/30 text-muted-foreground hover:bg-secondary/60 hover:text-foreground transition-colors flex items-center justify-center gap-1.5 disabled:opacity-40 disabled:cursor-not-allowed"
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
        <span className="flex-1 text-sm truncate" title={group.group_name}>
          {group.group_name}
        </span>
        <GroupRowCounts group={group} />
      </button>
      {hasGroupActions && <GroupRowMenu groupId={group.id} />}
    </div>
  )
}

/** A group whose files haven't arrived yet: listed, and clicking it loads it next. */
interface PendingGroupRowProps {
  group: GroupSummary
  awaited: boolean
  onOpen: (groupId: number) => void
  onDemand: boolean
}

function PendingGroupRow({ group, awaited, onOpen, onDemand }: PendingGroupRowProps) {
  const { sortedOut } = useEditGroupContext()
  return (
    <button
      onClick={() => onOpen(group.id)}
      aria-busy={awaited}
      title={onDemand ? undefined : 'Still loading — click to load it next'}
      className="w-full flex items-center gap-2 pl-3 pr-2 py-2 text-left min-w-0 border-l-2 border-transparent text-muted-foreground/70 hc:text-muted-foreground hover:text-foreground hover:bg-secondary/50 transition-colors"
    >
      <span className="flex-1 text-sm truncate" title={group.base_name}>
        {group.base_name}
      </span>
      <span className="text-xs shrink-0 flex items-center gap-1">
        <TypeCounts
          maps={group.map_count}
          scenes={group.scene_count}
          skipped={sortedOut.counts[group.id] ?? 0}
        />
        {awaited && <Loader2 className="h-3 w-3 animate-spin ml-1" />}
      </span>
    </button>
  )
}

/** In-scope images by type, images Auto skipped, out-of-scope extras, and the
 * auto-save indicator. */
function GroupRowCounts({ group }: { group: EditableGroupState }) {
  const { ops, sortedOut } = useEditGroupContext()
  const inScope = group.files.filter((f) => !f.excluded && !f.outOfScope)
  const scenes = inScope.filter((f) => f.image_type === 'scene').length
  const outOfScope = group.files.filter((f) => f.outOfScope).length
  const dbId = serverId(group.id)
  const skipped = dbId === null ? 0 : (sortedOut.counts[dbId] ?? 0)

  return (
    <span className="text-xs text-muted-foreground shrink-0 flex items-center gap-1">
      <TypeCounts maps={inScope.length - scenes} scenes={scenes} skipped={skipped} />
      {outOfScope > 0 && (
        <span className="ml-0.5 opacity-80 hc:opacity-100 tabular-nums">+{outOfScope}</span>
      )}
      {ops.groupSaving.has(group.id) ? (
        <Loader2 className="h-3 w-3 animate-spin text-muted-foreground ml-1" />
      ) : ops.groupSaved.has(group.id) ? (
        <Check className="h-3 w-3 text-success ml-1" />
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
  const button = 'px-2 py-0.5 rounded border text-3xs transition-colors disabled:opacity-50'
  return (
    <div className="px-3 py-2 border-l-2 border-destructive/50 bg-destructive/5">
      <p className="text-2xs text-destructive/80 mb-1.5">Delete this group?</p>
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
