import { type ReactNode } from 'react'
import { Loader2, ImageIcon, Layers } from 'lucide-react'
import { getThumbnailUrlById } from '@/lib/api'
import type { GroupPickerItem } from '@/types'

interface GroupPickerResultsProps {
  groups: GroupPickerItem[]
  isLoading: boolean
  selectedId: number | null
  onSelect: (group: GroupPickerItem) => void
  /** Shown when there are no groups to list */
  emptyLabel: string
  /** Rows above the groups (e.g. "New group"); shown while loading and when empty too */
  leading?: ReactNode
}

/** The list inside a `GroupPickerShell`: one selectable row per group. */
export function GroupPickerResults({
  groups,
  isLoading,
  selectedId,
  onSelect,
  emptyLabel,
  leading,
}: GroupPickerResultsProps) {
  // With a leading row the list is never empty, so the placeholders are kept small.
  const placeholderHeight = leading ? 'h-24' : 'h-[11.76rem]'
  return (
    <div className="space-y-px">
      {leading}
      {isLoading ? (
        <div className={`flex items-center justify-center ${placeholderHeight}`}>
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        </div>
      ) : groups.length === 0 ? (
        <div
          className={`flex flex-col items-center justify-center ${placeholderHeight} text-muted-foreground`}
        >
          <Layers className="h-8 w-8 mb-2 opacity-40" />
          <p className="text-sm">{emptyLabel}</p>
        </div>
      ) : (
        groups.map((group) => (
          <GroupPickerRow
            key={group.id}
            selected={selectedId === group.id}
            onClick={() => onSelect(group)}
            thumbnail={
              group.primary_image_id && (
                <img
                  src={getThumbnailUrlById(group.primary_image_id)}
                  alt=""
                  loading="eager"
                  onError={(e) => {
                    e.currentTarget.style.display = 'none'
                  }}
                  className="absolute inset-0 h-full w-full object-cover"
                />
              )
            }
            title={group.base_name}
            subtitle={group.author}
            badge={group.image_count}
          />
        ))
      )}
    </div>
  )
}

interface GroupPickerRowProps {
  selected: boolean
  onClick: () => void
  title: string
  subtitle?: string | null
  /** Covers the placeholder icon when given */
  thumbnail?: ReactNode
  /** Placeholder icon; defaults to an image icon */
  icon?: ReactNode
  badge?: number
}

export function GroupPickerRow({
  selected,
  onClick,
  title,
  subtitle,
  thumbnail,
  icon,
  badge,
}: GroupPickerRowProps) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={onClick}
      className={`w-full flex items-center gap-3 px-3 py-2 rounded-md text-left transition-all duration-100 ${
        selected ? 'bg-primary/15 ring-1 ring-primary/40' : 'hover:bg-muted/50'
      }`}
    >
      <div className="h-8 w-8 shrink-0 rounded overflow-hidden bg-muted/60 border border-border/30 relative">
        <div className="absolute inset-0 flex items-center justify-center">
          {icon ?? <ImageIcon className="h-3.5 w-3.5 text-muted-foreground" />}
        </div>
        {thumbnail}
      </div>

      <div className="flex-1 min-w-0">
        <p
          className={`text-xs font-medium leading-tight truncate ${
            selected ? 'text-primary' : 'text-foreground'
          }`}
        >
          {title}
        </p>
        {subtitle && <p className="text-2xs text-muted-foreground truncate mt-0.5">{subtitle}</p>}
      </div>

      {badge !== undefined && (
        <span className="shrink-0 px-1.5 py-px rounded-full bg-primary/15 text-3xs font-medium text-primary tabular-nums">
          {badge}
        </span>
      )}
    </button>
  )
}
