/**
 * The import dialog's progress view, below the frame (design/import-progress.md §3):
 * one overall bar with the files done and the time left, then "Identifying groups" once
 * every file is settled, and any problems in a line. The groups are the report's, once
 * they have been identified (ADR-028).
 */

import { Loader2 } from 'lucide-react'
import type { ImportCounts, ImportJobSummary } from '@/lib/import/types'
import { finishedCount, plural, timeLeftText } from './format'

interface ProgressSummaryProps {
  job: ImportJobSummary
  secondsPerItem: number | null | undefined
}

/** The bar, and under it: files done and the time left, or the grouping phase. */
export function ProgressSummary({ job, secondsPerItem }: ProgressSummaryProps) {
  const { counts } = job
  const grouping = job.status === 'grouping'
  const parts = [
    `${finishedCount(counts).toLocaleString()} of ${plural(counts.total, 'file')} done`,
  ]
  const timeLeft = timeLeftText(counts, secondsPerItem)
  if (timeLeft) parts.push(timeLeft)
  return (
    <div className="space-y-2">
      <ProgressMeter
        received={counts.total - counts.awaiting_bytes}
        finished={finishedCount(counts)}
        total={counts.total}
        settling={grouping}
      />
      {job.planned &&
        (grouping ? (
          <p className="flex items-center gap-2 text-xs text-foreground/90 hc:text-foreground">
            <Loader2
              className="h-3 w-3 animate-spin motion-reduce:animate-none text-primary"
              aria-hidden
            />
            Identifying groups…
          </p>
        ) : (
          <p className="text-xs text-foreground/90 hc:text-foreground">{parts.join(' · ')}</p>
        ))}
    </div>
  )
}

/**
 * One track, two layers: how much the server has received (quiet) and how much
 * is finished (amber). The gap between them is work waiting to be processed. While the
 * groups are identified (``settling``) the full bar breathes.
 */
function ProgressMeter({
  received,
  finished,
  total,
  settling = false,
}: {
  received: number
  finished: number
  total: number
  settling?: boolean
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
          className={`absolute inset-y-0 left-0 bg-primary/80 transition-[width] duration-700 ease-out ${
            settling ? 'animate-pulse motion-reduce:animate-none' : ''
          }`}
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
