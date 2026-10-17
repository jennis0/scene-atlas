/**
 * The import's groups as a ruled ledger that fills in as images land: group
 * name in Cinzel, a mono count in the margin, and one amber hairline per row.
 * Virtualised, because a big folder can plan thousands of groups.
 */

import { useRef } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import { finishedCount } from './format'
import type { ImportGroupSummary } from '@/lib/import/types'

const ROW_HEIGHT = 48

interface GroupLedgerProps {
  groups: ImportGroupSummary[]
  /** Open the group in the gallery editor (finished groups that produced images). */
  onOpenGroup?: (imageGroupId: number) => void
}

export function GroupLedger({ groups, onOpenGroup }: GroupLedgerProps) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const virtualizer = useVirtualizer({
    count: groups.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_HEIGHT,
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
        {virtualizer.getVirtualItems().map((row) => (
          <LedgerRow
            key={groups[row.index].id}
            group={groups[row.index]}
            top={row.start}
            onOpenGroup={onOpenGroup}
          />
        ))}
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
