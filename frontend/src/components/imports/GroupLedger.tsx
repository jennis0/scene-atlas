/**
 * The import's groups as a ruled ledger. Two modes:
 * - progress (while importing): fills in as images land, with a count in the
 *   margin and one hairline progress bar per row.
 * - report (once finished): compact rows with a cover thumbnail, the image
 *   count, and only the exceptions worth reading (failed, already in library,
 *   added to an existing group).
 * Virtualised, because a big folder can plan thousands of groups.
 */

import { useRef, useState } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import { getThumbnailUrlById } from '@/lib/api'
import { finishedCount, plural } from './format'
import type { ImportGroupSummary } from '@/lib/import/types'

const ROW_HEIGHT = 48
const REPORT_ROW_HEIGHT = 44

interface GroupLedgerProps {
  groups: ImportGroupSummary[]
  /** Open the group in the editor (groups that produced images). */
  onOpenGroup?: (imageGroupId: number) => void
  variant?: 'progress' | 'report'
  /** Report mode: show each group's author (off when they all share one) */
  showAuthor?: boolean
}

export function GroupLedger({
  groups,
  onOpenGroup,
  variant = 'progress',
  showAuthor = true,
}: GroupLedgerProps) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const rowHeight = variant === 'report' ? REPORT_ROW_HEIGHT : ROW_HEIGHT
  const virtualizer = useVirtualizer({
    count: groups.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => rowHeight,
    overscan: 8,
    initialRect: { width: 640, height: 480 }, // render rows before the first measure
  })

  if (groups.length === 0) {
    return (
      <p className="px-6 py-8 text-center text-[13px] text-muted-foreground">
        Groups appear here once the file list has been sorted.
      </p>
    )
  }

  return (
    <div ref={scrollRef} className="flex-1 min-h-0 overflow-y-auto px-6" role="list">
      <div style={{ height: virtualizer.getTotalSize(), position: 'relative' }}>
        {virtualizer
          .getVirtualItems()
          .map((row) =>
            variant === 'report' ? (
              <ReportRow
                key={groups[row.index].id}
                group={groups[row.index]}
                top={row.start}
                showAuthor={showAuthor}
                onOpenGroup={onOpenGroup}
              />
            ) : (
              <LedgerRow
                key={groups[row.index].id}
                group={groups[row.index]}
                top={row.start}
                onOpenGroup={onOpenGroup}
              />
            ),
          )}
      </div>
    </div>
  )
}

function LedgerRow({
  group,
  top,
  onOpenGroup,
}: {
  group: ImportGroupSummary
  top: number
  onOpenGroup?: (imageGroupId: number) => void
}) {
  const { counts } = group
  const finished = finishedCount(counts)
  const ratio = counts.total > 0 ? finished / counts.total : 0
  const open = counts.processing > 0 || counts.ready > 0 || counts.awaiting_bytes > 0
  const canOpen = !!onOpenGroup && group.image_group_id !== null && counts.done > 0
  // Count against what this import could add: files already in the library or
  // skipped are settled, not missing, so a finished group never reads "3/6".
  const importable = counts.total - counts.duplicate - counts.skipped

  const content = (
    <>
      <div className="flex items-baseline gap-3 min-w-0">
        <span
          className={`font-display text-[15px] truncate ${open ? 'text-foreground' : 'text-foreground/80'}`}
          title={group.group_name}
        >
          {group.group_name}
        </span>
        <span className="text-[11px] text-muted-foreground truncate shrink min-w-0">
          {group.author}
          {group.merged_into_existing && (
            <span className="italic text-muted-foreground">, adds to an existing group</span>
          )}
        </span>
        <span className="ml-auto flex items-baseline gap-2 shrink-0 font-mono text-[10.5px] tabular-nums">
          {counts.duplicate > 0 && (
            <span className="text-muted-foreground">{counts.duplicate} in library</span>
          )}
          {counts.failed > 0 && <span className="text-destructive">{counts.failed} failed</span>}
          <span className="text-muted-foreground">
            {counts.done}
            <span className="text-muted-foreground">/{importable}</span>
          </span>
        </span>
      </div>
      <div className="mt-1.5 h-px bg-border/40 overflow-hidden" aria-hidden>
        <div
          className={`h-full transition-[width] duration-700 ease-out ${
            open ? 'bg-primary/80' : 'bg-primary/35'
          }`}
          style={{ width: `${Math.round(ratio * 100)}%` }}
        />
      </div>
    </>
  )

  const style = { position: 'absolute' as const, top, left: 0, right: 0, height: ROW_HEIGHT }
  if (canOpen) {
    return (
      <button
        role="listitem"
        style={{ ...style, left: -8, right: -8 }}
        onClick={() => onOpenGroup(group.image_group_id!)}
        title="Open in the group editor"
        className="text-left flex flex-col justify-center px-2 rounded-md hover:bg-muted/30"
      >
        {content}
      </button>
    )
  }
  return (
    <div role="listitem" style={style} className="flex flex-col justify-center">
      {content}
    </div>
  )
}

function ReportRow({
  group,
  top,
  showAuthor,
  onOpenGroup,
}: {
  group: ImportGroupSummary
  top: number
  showAuthor: boolean
  onOpenGroup?: (imageGroupId: number) => void
}) {
  const { counts } = group
  const [thumbFailed, setThumbFailed] = useState(false)
  const canOpen = !!onOpenGroup && group.image_group_id !== null && counts.done > 0
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
        <span
          className="font-display text-[15px] text-foreground truncate"
          title={group.group_name}
        >
          {group.group_name}
        </span>
        {showAuthor && group.author && (
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
        <span>{plural(counts.done, 'image')}</span>
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
  if (canOpen) {
    return (
      <button
        role="listitem"
        style={{ ...style, left: -8, right: -8 }}
        onClick={() => onOpenGroup(group.image_group_id!)}
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
