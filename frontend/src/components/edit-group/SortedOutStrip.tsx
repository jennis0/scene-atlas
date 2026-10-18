/**
 * In the group editor: the images Auto skipped from this group when it was imported
 * (tokens, other art, and images it couldn't place), so they can be checked and
 * included (design/ingestion.md §5.6). Collapsed to one line until asked. Included
 * images go through the import queue; the editor adds them to the group once they're
 * imported (useSortedOut). Keyed by group, so another group starts collapsed.
 */

import { useEffect, useId, useState } from 'react'
import { ImageOff, Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { TextButton } from '@/components/imports/ImportFrame'
import { plural } from '@/components/imports/format'
import { importPreviewUrl } from '@/lib/api/urls'
import { getImportManager } from '@/lib/import/ImportManager'
import type { ImportItem } from '@/lib/import/types'

interface SortedOutStripProps {
  /** The gallery group */
  groupId: number
  /** From the sorted-out counts; the strip renders nothing at 0 */
  count: number
  /** Included images from this group still being imported */
  importing: number
  /** Images were included, re-opening these imports */
  onIncluded: (count: number, jobIds: string[]) => void
}

interface SortedOutList {
  /** null until the first load; refreshes replace it in place */
  items: ImportItem[] | null
  /** The server sends the first few hundred; the strip's `count` is how many in all */
  truncated: boolean
  error: boolean
  busy: boolean
  refresh: () => void
  include: (ids: number[]) => Promise<void>
}

/**
 * The group's skipped images, loaded while the strip is open. Re-reads keep what's shown
 * until the fresh list arrives, so the strip keeps its scroll position.
 */
function useSortedOutList(
  groupId: number,
  open: boolean,
  onIncluded: SortedOutStripProps['onIncluded'],
): SortedOutList {
  const [items, setItems] = useState<ImportItem[] | null>(null)
  const [truncated, setTruncated] = useState(false)
  const [error, setError] = useState(false)
  const [busy, setBusy] = useState(false)
  const [version, setVersion] = useState(0)

  useEffect(() => {
    if (!open) return
    let cancelled = false
    setError(false)
    getImportManager()
      .listSortedOut(groupId)
      .then((list) => {
        if (cancelled) return
        setItems(list.items)
        setTruncated(list.truncated)
      })
      .catch(() => !cancelled && setError(true))
    return () => {
      cancelled = true
    }
  }, [open, groupId, version])

  const refresh = () => setVersion((v) => v + 1)

  const include = async (ids: number[]) => {
    setBusy(true)
    try {
      const result = await getImportManager().include(ids)
      // Drop them in place, then re-read: a truncated list brings in the next ones
      setItems((prev) => prev?.filter((i) => !ids.includes(i.id)) ?? null)
      refresh()
      onIncluded(result.affected, result.job_ids)
      toast.success(`Importing ${plural(result.affected, 'image')}`, {
        description: 'They will appear in this group once imported.',
      })
    } catch {
      toast.error("Couldn't include them", { description: 'The server could not be reached.' })
    } finally {
      setBusy(false)
    }
  }

  return { items, truncated, error, busy, refresh, include }
}

export function SortedOutStrip({ groupId, count, importing, onIncluded }: SortedOutStripProps) {
  const listId = useId()
  const [open, setOpen] = useState(false)
  const list = useSortedOutList(groupId, open, onIncluded)

  if (count === 0 && importing === 0) return null

  return (
    <div className="border-b border-border/30">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2 text-xs">
        <ImageOff className="h-3.5 w-3.5 text-muted-foreground shrink-0" aria-hidden />
        <StripStatus count={count} importing={importing} />
        <StripControls
          list={list}
          count={count}
          open={open}
          listId={listId}
          onToggle={() => setOpen((o) => !o)}
        />
      </div>
      {open && count > 0 && (
        <div id={listId} className="pb-3">
          <StripList list={list} count={count} />
        </div>
      )}
    </div>
  )
}

function StripControls({
  list,
  count,
  open,
  listId,
  onToggle,
}: {
  list: SortedOutList
  count: number
  open: boolean
  listId: string
  onToggle: () => void
}) {
  const { items } = list
  return (
    <span className="ml-auto flex items-center gap-1">
      {open && items && items.length > 1 && (
        <TextButton
          tone="primary"
          onClick={() => void list.include(items.map((i) => i.id))}
          disabled={list.busy}
        >
          {list.truncated ? `Include these ${items.length.toLocaleString()}` : 'Include all'}
        </TextButton>
      )}
      {count > 0 && (
        <TextButton onClick={onToggle} aria-expanded={open} aria-controls={listId}>
          {open ? 'Hide' : 'Review'}
        </TextButton>
      )}
    </span>
  )
}

function StripStatus({ count, importing }: { count: number; importing: number }) {
  return (
    <span role="status" className="flex flex-wrap gap-x-1">
      <span className="text-foreground/90 hc:text-foreground">
        {count > 0
          ? `${plural(count, 'image')} from this group ${count === 1 ? 'was' : 'were'} skipped by Auto`
          : 'No skipped images left'}
      </span>
      {importing > 0 && (
        <span className="text-muted-foreground">· {importing.toLocaleString()} being imported</span>
      )}
    </span>
  )
}

function StripList({ list, count }: { list: SortedOutList; count: number }) {
  const { items } = list
  if (list.error) {
    return (
      <p className="text-xs text-muted-foreground">
        Couldn't load them.{' '}
        <button className="text-primary hover:underline" onClick={list.refresh}>
          Try again
        </button>
      </p>
    )
  }
  if (items === null) {
    return (
      <Loader2
        className="h-4 w-4 animate-spin text-muted-foreground"
        role="img"
        aria-label="Loading skipped images"
      />
    )
  }
  return (
    <>
      <ul className="flex gap-3 overflow-x-auto pb-1">
        {items.map((item) => (
          <SortedOutTile
            key={item.id}
            item={item}
            busy={list.busy}
            onInclude={() => void list.include([item.id])}
          />
        ))}
      </ul>
      {list.truncated && (
        <p className="mt-1 text-2xs text-muted-foreground">
          Showing the first {items.length.toLocaleString()} of {count.toLocaleString()}. The rest
          appear as you include these, or find them in each import's report, under Skipped.
        </p>
      )}
    </>
  )
}

function SortedOutTile({
  item,
  busy,
  onInclude,
}: {
  item: ImportItem
  busy: boolean
  onInclude: () => void
}) {
  return (
    <li className="w-24 shrink-0 flex flex-col gap-1" title={item.relative_path}>
      <div className="h-24 w-24 rounded bg-secondary overflow-hidden flex items-center justify-center">
        {item.has_preview ? (
          <img
            src={importPreviewUrl(item)}
            alt=""
            loading="lazy"
            className="max-h-full max-w-full object-contain"
          />
        ) : (
          <ImageOff className="h-5 w-5 text-muted-foreground" aria-hidden />
        )}
      </div>
      <span className="font-mono text-3xs text-muted-foreground truncate">{item.filename}</span>
      <span className="text-3xs text-muted-foreground leading-tight line-clamp-2">
        {item.error_reason}
      </span>
      {/* At the foot, so buttons line up when a reason wraps */}
      <span className="mt-auto">
        <TextButton onClick={onInclude} disabled={busy} aria-label={`Include ${item.filename}`}>
          Include
        </TextButton>
      </span>
    </li>
  )
}
