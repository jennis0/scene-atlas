/**
 * In the group editor opened on an import: says whether the import is still running,
 * goes back to its progress, and adds the groups it has finished since the editor
 * opened, when asked (design/import-progress.md §5). Never adds them on its own, so
 * rows don't move under the user.
 */

import { useState } from 'react'
import { Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { TextButton } from '@/components/imports/ImportFrame'
import { finishedCount, isFinished, plural } from '@/components/imports/format'
import { getImportManager } from '@/lib/import/ImportManager'
import { useImportJob } from '@/lib/import/useImports'

interface ImportRunningStripProps {
  jobId: string
  /** The groups the editor already has */
  reviewedGroupIds: number[]
  onAddGroups?: (groupIds: number[]) => void
  onShowProgress?: () => void
}

export function ImportRunningStrip({
  jobId,
  reviewedGroupIds,
  onAddGroups,
  onShowProgress,
}: ImportRunningStripProps) {
  const { job } = useImportJob(jobId)
  const [adding, setAdding] = useState(false)
  // Reviewable groups when the last "Add" ran. A group the editor has can leave the count
  // again (an include re-opens its import), so the editor's own id count can't tell
  // what's new once the user has added some.
  const [counted, setCounted] = useState<number | null>(null)
  if (!job) return null

  const finished = isFinished(job)
  const ready = Math.max(0, job.groups_reviewable - (counted ?? reviewedGroupIds.length))
  if (finished && ready === 0) return null

  const addGroups = async () => {
    setAdding(true)
    try {
      const reviewed = new Set(reviewedGroupIds)
      const detail = await getImportManager().getDetail(jobId)
      setCounted(detail.reviewable_group_ids.length)
      const added = detail.reviewable_group_ids.filter((id) => !reviewed.has(id))
      if (added.length > 0) onAddGroups?.(added)
    } catch {
      toast.error("Couldn't add the new groups", {
        description: 'The server could not be reached.',
      })
    } finally {
      setAdding(false)
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-6 py-2 border-b border-border/30 bg-primary/[0.05] text-xs">
      <span className="flex items-center gap-2 text-foreground/90 hc:text-foreground">
        {!finished && <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" aria-hidden />}
        <span role="status">
          {finished
            ? `Import finished · ${plural(job.group_count, 'group')}`
            : job.status === 'grouping'
              ? 'Import still running · identifying groups'
              : `Import still running · ${finishedCount(job.counts).toLocaleString()} of ${plural(job.counts.total, 'file')} done`}
        </span>
      </span>
      {ready > 0 && onAddGroups && (
        <span className="flex items-center gap-2 text-muted-foreground">
          {ready === 1
            ? '1 more group is ready'
            : `${ready.toLocaleString()} more groups are ready`}
          <TextButton tone="primary" onClick={() => void addGroups()} disabled={adding}>
            Add {ready === 1 ? 'it' : 'them'}
          </TextButton>
        </span>
      )}
      {!finished && onShowProgress && (
        <span className="ml-auto">
          <TextButton onClick={onShowProgress}>Show progress</TextButton>
        </span>
      )}
    </div>
  )
}
