import { Pencil, X } from 'lucide-react'

export interface SubgroupHeadingProps {
  /** null = no-label section, displayed as "Main". null sections are never editable. */
  subgroup: string | null
  /** Non-excluded file count shown on the right */
  count: number
  /** Whether this heading's input is active (parent controls which one is open) */
  isEditing: boolean
  /** Current input value when editing */
  draft: string
  onDraftChange: (val: string) => void
  /** Called when the pencil icon is clicked */
  onStartEdit: () => void
  /** Called on Enter or blur — parent should commit the rename */
  onCommit: () => void
  /** Called on Escape */
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
  draft,
  onDraftChange,
  onStartEdit,
  onCommit,
  onCancel,
  onClear,
  canEdit,
}: SubgroupHeadingProps) {
  const showActions = canEdit && subgroup !== null && !isEditing

  return (
    <div className="flex items-center gap-2 py-1.5 mt-2 first:mt-0">
      {isEditing ? (
        <input
          value={draft}
          autoFocus
          onChange={(e) => onDraftChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') onCommit()
            if (e.key === 'Escape') onCancel()
          }}
          onBlur={onCommit}
          className="text-[11px] font-semibold text-foreground border-b border-primary/70 bg-transparent outline-none uppercase tracking-wider capitalize"
        />
      ) : (
        <span className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider capitalize whitespace-nowrap">
          {subgroup ?? 'Main'}
        </span>
      )}

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
    </div>
  )
}
