/**
 * In the group editor: the images Auto skipped from this group when it was imported
 * (tokens, other art, and images it couldn't place), so they can be checked and
 * included (design/ingestion.md §5.6). Collapsed to one line until asked; included
 * images go through the import queue and are in the group the next time it opens,
 * rather than appearing under the user mid-edit.
 */

import { useEffect, useState } from 'react'
import { Loader2, ScanSearch } from 'lucide-react'
import { toast } from 'sonner'
import { TextButton } from '@/components/imports/ImportFrame'
import { plural } from '@/components/imports/format'
import { getImportManager } from '@/lib/import/ImportManager'
import { previewUrl } from '@/lib/import/importClient'
import type { ImportItem } from '@/lib/import/types'

interface SortedOutStripProps {
  /** The gallery group */
  groupId: number
  /** From the sorted-out counts; the strip renders nothing at 0 */
  count: number
  /** Re-read the counts after an include */
  onIncluded: () => void
}

export function SortedOutStrip({ groupId, count, onIncluded }: SortedOutStripProps) {
  const [open, setOpen] = useState(false)
  const [items, setItems] = useState<ImportItem[] | null>(null)
  const [truncated, setTruncated] = useState(false)
  const [error, setError] = useState(false)
  const [busy, setBusy] = useState(false)
  const [included, setIncluded] = useState(0)

  // A different group: start collapsed, and load its list only when opened
  useEffect(() => {
    setOpen(false)
    setItems(null)
    setIncluded(0)
  }, [groupId])

  useEffect(() => {
    if (!open || items !== null) return
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
  }, [open, items, groupId])

  if (count === 0 && included === 0) return null

  const include = async (ids: number[]) => {
    setBusy(true)
    try {
      const n = await getImportManager().include(ids)
      setItems((prev) => prev?.filter((i) => !ids.includes(i.id)) ?? null)
      setIncluded((prev) => prev + n)
      onIncluded()
      toast.success(`Importing ${plural(n, 'image')}`, {
        description: 'They will be in this group the next time you open it.',
      })
    } catch {
      toast.error("Couldn't include them", { description: 'The server could not be reached.' })
    } finally {
      setBusy(false)
    }
  }

  const remaining = items?.length ?? count
  return (
    <div className="border-b border-border/30">
      <div role="status" className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2 text-xs">
        <ScanSearch className="h-3.5 w-3.5 text-muted-foreground shrink-0" aria-hidden />
        <span className="text-foreground/90 hc:text-foreground">
          {remaining > 0
            ? `${plural(remaining, 'image')} from this group ${remaining === 1 ? 'was' : 'were'} skipped by Auto`
            : 'No skipped images left'}
        </span>
        {included > 0 && (
          <span className="text-muted-foreground">
            · {included.toLocaleString()} being imported
          </span>
        )}
        <span className="ml-auto flex items-center gap-1">
          {open && items && items.length > 1 && (
            <TextButton
              tone="primary"
              onClick={() => void include(items.map((i) => i.id))}
              disabled={busy}
            >
              Include all
            </TextButton>
          )}
          {remaining > 0 && (
            <TextButton onClick={() => setOpen((o) => !o)}>{open ? 'Hide' : 'Review'}</TextButton>
          )}
        </span>
      </div>

      {open && remaining > 0 && (
        <div className="pb-3">
          {error ? (
            <p className="text-xs text-muted-foreground">
              Couldn't load them.{' '}
              <button className="text-primary hover:underline" onClick={() => setItems(null)}>
                Try again
              </button>
            </p>
          ) : items === null ? (
            <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
          ) : (
            <>
              <ul className="flex gap-3 overflow-x-auto pb-1">
                {items.map((item) => (
                  <SortedOutTile
                    key={item.id}
                    item={item}
                    busy={busy}
                    onInclude={() => void include([item.id])}
                  />
                ))}
              </ul>
              {truncated && (
                <p className="mt-1 text-2xs text-muted-foreground">
                  Showing the first {items.length.toLocaleString()}. The rest are in each import's
                  report, under Skipped.
                </p>
              )}
            </>
          )}
        </div>
      )}
    </div>
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
    <li className="w-[6rem] shrink-0 flex flex-col gap-1" title={item.relative_path}>
      <div className="h-[6rem] w-[6rem] rounded bg-secondary overflow-hidden flex items-center justify-center">
        {item.has_preview ? (
          <img
            src={previewUrl(item)}
            alt=""
            loading="lazy"
            className="max-h-full max-w-full object-contain"
          />
        ) : (
          <ScanSearch className="h-5 w-5 text-muted-foreground" aria-hidden />
        )}
      </div>
      <span className="font-mono text-3xs text-muted-foreground truncate">{item.filename}</span>
      <span className="text-3xs text-muted-foreground leading-tight line-clamp-2">
        {item.error_reason}
      </span>
      <TextButton onClick={onInclude} disabled={busy}>
        Include
      </TextButton>
    </li>
  )
}
