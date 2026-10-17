/**
 * The import dialog's progress view, below the frame (design/import-progress.md §3):
 * one overall bar with the groups done and the time left, the few groups importing
 * now, and any problems in a line. The full group list is the report, once it's done.
 */

import { ACTIVE_GROUPS } from '@/lib/import/importClient'
import type { ImportCounts, ImportGroupSummary, ImportJobSummary } from '@/lib/import/types'
import { finishedCount, plural, timeLeftText } from './format'

interface ProgressSummaryProps {
  job: ImportJobSummary
  secondsPerItem: number | null | undefined
}

/** The bar, and under it: groups done and the time left. */
export function ProgressSummary({ job, secondsPerItem }: ProgressSummaryProps) {
  const { counts } = job
  const parts = [`${job.groups_done.toLocaleString()} of ${plural(job.group_count, 'group')} done`]
  const timeLeft = timeLeftText(counts, secondsPerItem)
  if (timeLeft) parts.push(timeLeft)
  return (
    <div className="space-y-2">
      <ProgressMeter
        received={counts.total - counts.awaiting_bytes}
        finished={finishedCount(counts)}
        total={counts.total}
      />
      {job.planned && <p className="text-xs text-foreground/90">{parts.join(' · ')}</p>}
    </div>
  )
}

/**
 * One track, two layers: how much the server has received (quiet) and how much
 * is finished (amber). The gap between them is work waiting to be processed.
 */
function ProgressMeter({
  received,
  finished,
  total,
}: {
  received: number
  finished: number
  total: number
}) {
  const pct = (n: number) => (total > 0 ? `${Math.round((n / total) * 100)}%` : '0%')
  return (
    <div>
      <div
        className="relative h-1 rounded-full bg-border/40 overflow-hidden"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={total}
        aria-valuenow={finished}
        aria-label="Files processed"
      >
        <div
          className="absolute inset-y-0 left-0 bg-foreground/15 transition-[width] duration-500"
          style={{ width: pct(received) }}
        />
        <div
          className="absolute inset-y-0 left-0 bg-primary/80 transition-[width] duration-700 ease-out"
          style={{ width: pct(finished) }}
        />
      </div>
      <div className="mt-1.5 flex justify-between font-mono text-2xs tabular-nums text-muted-foreground">
        <span>{received.toLocaleString()} received</span>
        <span>
          {finished.toLocaleString()}
          <span className="text-muted-foreground"> / {total.toLocaleString()} processed</span>
        </span>
      </div>
    </div>
  )
}

interface NowImportingProps {
  /** The first groups with files still to import, in processing order */
  groups: ImportGroupSummary[]
  planned: boolean
}

export function NowImporting({ groups, planned }: NowImportingProps) {
  if (!planned || groups.length === 0) return null
  return (
    <section aria-labelledby="now-importing" className="space-y-1">
      <h3 id="now-importing" className="text-xs text-muted-foreground">
        Now importing
      </h3>
      <ul>
        {groups.slice(0, ACTIVE_GROUPS).map((group) => (
          <ImportingGroupRow key={group.id} group={group} />
        ))}
      </ul>
    </section>
  )
}

function ImportingGroupRow({ group }: { group: ImportGroupSummary }) {
  const { counts } = group
  // Count against what this import could add: files already in the library or
  // skipped are settled, not missing, so a finished group never reads "3/6".
  const importable = counts.total - counts.duplicate - counts.skipped
  const ratio = counts.total > 0 ? finishedCount(counts) / counts.total : 0
  const started = counts.processing > 0 || finishedCount(counts) > 0
  return (
    <li className="py-2">
      <div className="flex items-baseline gap-3 min-w-0">
        <span className="font-display text-sm truncate" title={group.group_name}>
          {group.group_name}
        </span>
        <span className="text-2xs text-muted-foreground truncate shrink min-w-0">
          {group.author}
        </span>
        <span className="ml-auto shrink-0 font-mono text-2xs tabular-nums text-muted-foreground">
          {started ? `${counts.done}/${importable}` : 'waiting'}
        </span>
      </div>
      <div className="mt-1.5 h-px bg-border/40 overflow-hidden" aria-hidden>
        <div
          className="h-full bg-primary/80 transition-[width] duration-700 ease-out"
          style={{ width: `${Math.round(ratio * 100)}%` }}
        />
      </div>
    </li>
  )
}

/** "98 already in your library · 3 failed", or nothing when there are no problems. */
export function ProblemsLine({ counts }: { counts: ImportCounts }) {
  if (counts.duplicate === 0 && counts.failed === 0) return null
  return (
    <p className="text-xs text-muted-foreground">
      {counts.duplicate > 0 && <>{counts.duplicate.toLocaleString()} already in your library</>}
      {counts.duplicate > 0 && counts.failed > 0 && ' · '}
      {counts.failed > 0 && (
        <span className="text-destructive">{counts.failed.toLocaleString()} failed</span>
      )}
      . The report lists them when the import finishes.
    </p>
  )
}
