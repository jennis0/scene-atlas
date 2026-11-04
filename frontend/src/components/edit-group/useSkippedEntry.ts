import { useEffect, useState } from 'react'
import { useImportJob } from '@/lib/import/useImports'
import { SKIPPED_START, type ReviewStart } from '@/lib/reviewStart'

export interface SkippedEntry {
  /** The import's skipped images that belong to no group (live, from the import list) */
  count: number
  /** The editor is showing the entry rather than a group */
  shown: boolean
  /** The sidebar lists the entry: there is something in it, or it's on screen */
  listed: boolean
  show: () => void
  hide: () => void
}

/**
 * The import review's Skipped entry: images Auto skipped that no group claims, so a
 * classifier mistake stays findable (design/variant-grouping.md §3). Only with a job.
 */
export function useSkippedEntry(
  jobId: string | undefined,
  open: boolean,
  start: ReviewStart | undefined,
): SkippedEntry {
  const { job } = useImportJob(jobId ?? null)
  const count = job?.ungrouped_sorted_out ?? 0
  const startShown = start === SKIPPED_START
  const [shown, setShown] = useState(startShown)

  useEffect(() => {
    if (open) setShown(startShown)
  }, [open, startShown])

  return {
    count,
    shown,
    listed: !!jobId && (count > 0 || shown),
    show: () => setShown(true),
    hide: () => setShown(false),
  }
}
