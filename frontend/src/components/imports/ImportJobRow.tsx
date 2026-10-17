/**
 * One import in the activity dock: status icon, label, a 3px progress track,
 * and a one-line status. Hover reveals pause/resume, or dismiss once finished.
 * Dismiss only hides the row; it never deletes anything, so it needs no confirm.
 */

import {
  AlertTriangle,
  Ban,
  Check,
  Loader2,
  Pause,
  PauseCircle,
  Play,
  Upload,
  X,
} from 'lucide-react'
import type { LocalUpload } from '@/lib/import/ImportManager'
import type { ImportJobSummary } from '@/lib/import/types'
import { isFinished, jobStatusText, processedRatio, uploadPhaseText } from './format'

interface ImportJobRowProps {
  job: ImportJobSummary
  upload: LocalUpload | undefined
  onOpen: () => void
  onPause: () => void
  onResume: () => void
  onDismiss: () => void
}

export function ImportJobRow({
  job,
  upload,
  onOpen,
  onPause,
  onResume,
  onDismiss,
}: ImportJobRowProps) {
  const finished = isFinished(job)
  const ratio = processedRatio(job.counts)
  const sending = uploadPhaseText(upload) !== null && !finished

  return (
    <div
      data-testid="import-job-card"
      className={`group/job relative rounded-md border transition-colors ${
        finished
          ? 'border-border/15 bg-muted/10 opacity-80 hover:opacity-100'
          : 'border-border/30 bg-secondary/20 hover:bg-secondary/40 hover:border-border/50'
      }`}
    >
      <button onClick={onOpen} className="block w-full text-left px-2.5 py-2 rounded-md">
        <div className="flex items-start gap-[7px] pr-12">
          <StatusIcon job={job} sending={sending} />
          <span
            className={`min-w-0 flex-1 text-[12px] font-medium truncate leading-tight ${
              finished ? 'text-muted-foreground' : 'text-foreground'
            }`}
            title={job.label ?? undefined}
          >
            {job.label ?? 'Import'}
          </span>
        </div>
        <div className="mt-[7px] h-[3px] rounded-full bg-border/30 overflow-hidden">
          <div
            className={`h-full rounded-full transition-[width] duration-700 ease-out ${
              finished ? 'bg-primary/45' : 'bg-primary/70'
            }`}
            style={{ width: `${Math.round(ratio * 100)}%` }}
          />
        </div>
        <div
          className={`mt-1 text-[10.5px] leading-tight truncate ${
            job.upload_interrupted ? 'text-primary' : 'text-muted-foreground'
          }`}
        >
          {jobStatusText(job, upload)}
        </div>
      </button>

      <div className="absolute top-1.5 right-1.5 flex items-center gap-0.5 opacity-0 group-hover/job:opacity-100 group-focus-within/job:opacity-100 transition-opacity">
        {job.status === 'active' && !finished && (
          <RowAction label="Pause" onClick={onPause} icon={<Pause className="h-3 w-3" />} />
        )}
        {job.status === 'paused' && (
          <RowAction label="Resume" onClick={onResume} icon={<Play className="h-3 w-3" />} />
        )}
        {finished && (
          <RowAction label="Dismiss" onClick={onDismiss} icon={<X className="h-3 w-3" />} />
        )}
      </div>
    </div>
  )
}

function RowAction({
  label,
  onClick,
  icon,
}: {
  label: string
  onClick: () => void
  icon: React.ReactNode
}) {
  return (
    <button
      onClick={onClick}
      title={label}
      className="h-5 w-5 rounded flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors"
    >
      {icon}
      <span className="sr-only">{label}</span>
    </button>
  )
}

function StatusIcon({ job, sending }: { job: ImportJobSummary; sending: boolean }) {
  const cls = 'h-3.5 w-3.5 shrink-0 mt-0.5'
  if (job.upload_interrupted) return <AlertTriangle className={`${cls} text-primary`} />
  if (job.status === 'paused') return <PauseCircle className={`${cls} text-muted-foreground`} />
  if (job.status === 'cancelled') return <Ban className={`${cls} text-muted-foreground`} />
  if (job.status === 'completed') {
    return job.counts.failed > 0 ? (
      <AlertTriangle className={`${cls} text-destructive/70`} />
    ) : (
      <Check className={`${cls} text-primary/70`} />
    )
  }
  if (sending) return <Upload className={`${cls} text-primary`} />
  return <Loader2 className={`${cls} text-primary animate-spin`} />
}
