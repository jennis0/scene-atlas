import { Pencil, X } from 'lucide-react'
import { SubgroupDropdown } from './SubgroupDropdown'

export interface SubgroupHeadingProps {
  /** null = no-label section, displayed as "Main". null sections are never editable. */
  subgroup: string | null
  /** Non-excluded file count shown on the right */
  count: number
  /** Whether this heading's picker is open (parent controls which one is active) */
  isEditing: boolean
  /** All existing subgroup labels in this group, used to populate the picker */
  existingSubgroups: string[]
  /** Called when the pencil icon is clicked */
  onStartEdit: () => void
  /** Called when the user picks a value — either an existing label or a typed name */
  onCommit: (value: string) => void
  /** Called on Escape or click outside */
  onCancel: () => void
  /** Called when the X button is clicked — removes label from all files */
  onClear: () => void
  /** When false, edit and clear buttons are hidden (AllTab mode or non-pending group) */
  canEdit: boolean
}

export function SubgroupHeading({
  subgroup,
  count,
  isEditing,
  existingSubgroups,
  onStartEdit,
  onCommit,
  onCancel,
  onClear,
  canEdit,
}: SubgroupHeadingProps) {
  const showActions = canEdit && subgroup !== null && !isEditing

  return (
    <div className="sticky top-0 z-10 bg-card relative flex items-center gap-2 py-1.5 mt-2 first:mt-0">
      <span className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider capitalize whitespace-nowrap">
        {subgroup ?? 'Main'}
      </span>

      {showActions && (
        <button
          onClick={onStartEdit}
          className="text-muted-foreground/40 hover:text-muted-foreground transition-colors"
          title={`Rename "${subgroup}"`}
        >
          <Pencil className="h-3 w-3" />
        </button>
      )}

      <div className="flex-1 h-px bg-border/30" />

      <span className="text-[11px] text-muted-foreground/40 tabular-nums">{count}</span>

      {showActions && (
        <button
          onClick={onClear}
          className="text-muted-foreground/40 hover:text-primary transition-colors"
          title={`Remove "${subgroup}" label from all files`}
        >
          <X className="h-3.5 w-3.5" />
        </button>
      )}

      <SubgroupDropdown
        isOpen={isEditing}
        existingSubgroups={existingSubgroups}
        initialValue={subgroup ?? ''}
        onCommit={onCommit}
        onCancel={onCancel}
      />
    </div>
  )
}
