/**
 * The finished import's groups as a ruled ledger (the report): compact rows with a
 * cover thumbnail, the images by type (TypeCounts: maps, scenes, skipped by Auto), and
 * only the exceptions worth reading (failed, already in library, added to an existing
 * group). Virtualised, because a big folder
 * can plan thousands of groups. While importing, the dialog shows only the groups
 * importing now (ImportProgress.tsx).
 */

import { useRef, useState } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import { getThumbnailUrlById } from '@/lib/api'
import { TypeCounts } from './TypeCounts'
import type { ImportGroupSummary } from '@/lib/import/types'

const REPORT_ROW_HEIGHT = 44

/** The row of the import's files that made no image and belong to no group */
export const UNGROUPED_LABEL = 'Not in a group'

interface GroupLedgerProps {
  groups: ImportGroupSummary[]
  /** Open the group in the editor (groups that produced images). */
  onOpenGroup?: (imageGroupId: number) => void
  /** Open the editor on the images Auto skipped that are in no group */
  onOpenSkipped?: () => void
  /** Report mode: show each group's author (off when they all share one) */
  showAuthor?: boolean
}

export function GroupLedger({
  groups,
  onOpenGroup,
  onOpenSkipped,
  showAuthor = true,
}: GroupLedgerProps) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const virtualizer = useVirtualizer({
    count: groups.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => REPORT_ROW_HEIGHT,
    overscan: 8,
    initialRect: { width: 640, height: 480 }, // render rows before the first measure
  })

  if (groups.length === 0) {
    return (
      <p className="px-6 py-8 text-center text-xs text-muted-foreground">
        Groups appear here once the file list has been sorted.
      </p>
    )
  }

  return (
    <div ref={scrollRef} className="flex-1 min-h-0 overflow-y-auto px-6" role="list">
      <div style={{ height: virtualizer.getTotalSize(), position: 'relative' }}>
        {virtualizer.getVirtualItems().map((row) => (
          <ReportRow
            key={groups[row.index].id}
            group={groups[row.index]}
            top={row.start}
            showAuthor={showAuthor}
            onOpenGroup={onOpenGroup}
            onOpenSkipped={onOpenSkipped}
          />
        ))}
      </div>
    </div>
  )
}

function ReportRow({
  group,
  top,
  showAuthor,
  onOpenGroup,
  onOpenSkipped,
}: {
  group: ImportGroupSummary
  top: number
  showAuthor: boolean
  onOpenGroup?: (imageGroupId: number) => void
  onOpenSkipped?: () => void
}) {
  const { counts } = group
  const [thumbFailed, setThumbFailed] = useState(false)
  const open = group.ungrouped
    ? counts.sorted_out > 0
      ? onOpenSkipped
      : undefined
    : onOpenGroup && group.image_group_id !== null && counts.done > 0
      ? () => onOpenGroup(group.image_group_id!)
      : undefined
  const name = group.ungrouped ? UNGROUPED_LABEL : group.group_name
  const notes = [
    counts.failed > 0 && { text: `${counts.failed} failed`, problem: true },
    counts.duplicate > 0 && { text: `${counts.duplicate} already in library`, problem: false },
    group.merged_into_existing && { text: 'added to an existing group', problem: false },
  ].filter((n): n is { text: string; problem: boolean } => !!n)

  const content = (
    <>
      <span className="transparency-backdrop h-[30px] w-10 shrink-0 overflow-hidden rounded-sm">
        {group.cover_image_id != null && !thumbFailed && (
          <img
            src={getThumbnailUrlById(group.cover_image_id)}
            alt=""
            width={40}
            height={30}
            loading="lazy"
            decoding="async"
            onError={() => setThumbFailed(true)}
            className="h-full w-full object-cover"
          />
        )}
      </span>
      <span className="min-w-0 flex-1 flex items-baseline gap-2">
        <span className="font-display text-sm text-foreground truncate" title={name}>
          {name}
        </span>
        {showAuthor && !group.ungrouped && group.author && (
          <span className="text-xs text-muted-foreground truncate shrink min-w-0">
            {group.author}
          </span>
        )}
      </span>
      <span className="shrink-0 flex items-baseline gap-2 text-xs text-muted-foreground tabular-nums">
        {notes.map((n) => (
          <span key={n.text} className={n.problem ? 'text-destructive' : undefined}>
            {n.text}
          </span>
        ))}
        <TypeCounts
          maps={group.map_count}
          scenes={group.scene_count}
          skipped={counts.sorted_out}
          className="self-center"
        />
      </span>
    </>
  )

  const style = {
    position: 'absolute' as const,
    top,
    left: 0,
    right: 0,
    height: REPORT_ROW_HEIGHT,
  }
  const className = 'flex items-center gap-3 border-b border-border/40'
  if (open) {
    return (
      <button
        role="listitem"
        style={{ ...style, left: -8, right: -8 }}
        onClick={open}
        title="Review in the editor"
        className={`${className} text-left px-2 rounded-md hover:bg-muted/30`}
      >
        {content}
      </button>
    )
  }
  return (
    <div role="listitem" style={style} className={className}>
      {content}
    </div>
  )
}
