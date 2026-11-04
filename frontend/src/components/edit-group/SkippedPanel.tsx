/**
 * The import review's Skipped entry: images Auto skipped that no group claims (no map's
 * folder or name points to them), listed by reason so a wrong call can be included. They
 * go through the import queue and are grouped once imported; the editor's running strip
 * offers any new groups (design/variant-grouping.md §3).
 */

import { TextButton } from '@/components/imports/ImportFrame'
import { getImportManager } from '@/lib/import/ImportManager'
import type { ImportItem } from '@/lib/import/types'
import { SortedOutListPending, SortedOutTile } from './SortedOutStrip'
import { useSortedOutList, type SortedOutList } from './useSortedOutList'

interface SkippedPanelProps {
  jobId: string
  /** From the import list: how many there are in all */
  count: number
}

export function SkippedPanel({ jobId, count }: SkippedPanelProps) {
  const list = useSortedOutList(
    {
      key: `import:${jobId}`,
      load: () => getImportManager().listSortedOutOfImport(jobId),
      includedNote: "They'll be grouped once imported.",
    },
    true,
    () => {},
  )
  const items = list.items

  return (
    <section aria-labelledby="skipped-panel-title" className="flex-1 min-h-0 flex flex-col">
      <div className="px-5 pt-4 pb-3 border-b border-border/30 shrink-0 flex items-start gap-4">
        <div className="flex-1 min-w-0">
          <h2 id="skipped-panel-title" className="font-display text-lg font-semibold">
            Skipped by Auto
          </h2>
          <p className="text-xs text-muted-foreground mt-0.5">
            These aren't in any group. Include any that Auto got wrong.
          </p>
        </div>
        {items && items.length > 1 && (
          <TextButton
            tone="primary"
            onClick={() => void list.include(items.map((i) => i.id))}
            disabled={list.busy}
          >
            {list.truncated ? `Include these ${items.length.toLocaleString()}` : 'Include all'}
          </TextButton>
        )}
      </div>
      <div className="flex-1 min-h-0 overflow-y-auto px-5 py-4">
        <PanelBody list={list} count={count} />
      </div>
    </section>
  )
}

function PanelBody({ list, count }: { list: SortedOutList; count: number }) {
  const { items } = list
  if (list.error || items === null) return <SortedOutListPending list={list} />
  if (items.length === 0) {
    return <p className="text-xs text-muted-foreground">Nothing left to check.</p>
  }
  return (
    <div className="space-y-5">
      {byReason(items).map(([reason, members]) => (
        <section key={reason} aria-label={reason}>
          <h3 className="section-label mb-2">
            {reason} <span className="tabular-nums">({members.length.toLocaleString()})</span>
          </h3>
          <ul className="flex flex-wrap gap-3">
            {members.map((item) => (
              <SortedOutTile
                key={item.id}
                item={item}
                busy={list.busy}
                onInclude={() => void list.include([item.id])}
                showReason={false}
              />
            ))}
          </ul>
        </section>
      ))}
      {list.truncated && (
        <p className="text-2xs text-muted-foreground">
          Showing the first {items.length.toLocaleString()} of {count.toLocaleString()}. The rest
          appear as you include these.
        </p>
      )}
    </div>
  )
}

/** Items by their reason, in order of first appearance */
function byReason(items: ImportItem[]): [string, ImportItem[]][] {
  const groups = new Map<string, ImportItem[]>()
  for (const item of items) {
    const reason = item.error_reason ?? 'Skipped'
    groups.set(reason, [...(groups.get(reason) ?? []), item])
  }
  return [...groups]
}
