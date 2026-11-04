import { useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import { plural } from '@/components/imports/format'
import { getImportManager } from '@/lib/import/ImportManager'
import type { ImportItem, SortedOutList as SortedOutPage } from '@/lib/import/types'

export interface SortedOutList {
  /** null until the first load; refreshes replace it in place */
  items: ImportItem[] | null
  /** The server sends the first few hundred; the strip's `count` is how many in all */
  truncated: boolean
  error: boolean
  busy: boolean
  refresh: () => void
  include: (ids: number[]) => Promise<void>
}

/** Where a list of skipped images comes from, and what to say once some are included */
export interface SortedOutSource {
  /** Changes when the list is another one (a group's, an import's) */
  key: string
  load: () => Promise<SortedOutPage>
  /** The included toast's description */
  includedNote: string
}

/**
 * Skipped images, loaded while `open`. Re-reads keep what's shown until the fresh list
 * arrives, so the list keeps its scroll position.
 */
export function useSortedOutList(
  source: SortedOutSource,
  open: boolean,
  onIncluded: (count: number, jobIds: string[]) => void,
): SortedOutList {
  const [items, setItems] = useState<ImportItem[] | null>(null)
  const [truncated, setTruncated] = useState(false)
  const [error, setError] = useState(false)
  const [busy, setBusy] = useState(false)
  const [version, setVersion] = useState(0)

  // Read through a ref: a new `load` identity each render must not re-run the effect
  const loadRef = useRef(source.load)
  loadRef.current = source.load

  useEffect(() => {
    if (!open) return
    let cancelled = false
    setError(false)
    loadRef
      .current()
      .then((list) => {
        if (cancelled) return
        setItems(list.items)
        setTruncated(list.truncated)
      })
      .catch(() => !cancelled && setError(true))
    return () => {
      cancelled = true
    }
  }, [open, source.key, version])

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
        description: source.includedNote,
      })
    } catch {
      toast.error("Couldn't include them", { description: 'The server could not be reached.' })
    } finally {
      setBusy(false)
    }
  }

  return { items, truncated, error, busy, refresh, include }
}
