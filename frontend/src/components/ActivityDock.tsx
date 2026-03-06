import { useState, useEffect } from 'react'
import {
  AlertTriangle,
  Loader2,
  Package,
  ChevronDown,
  Trash2,
  X,
  Check,
  AlertCircle,
  Clock,
  Ban,
  Upload,
  Cog,
  WifiOff,
} from 'lucide-react'
import { importApi } from '@/lib/api'
import type { ActiveImportJob } from '@/hooks/useActiveImports'
import type { BackgroundJob } from '@/types'

interface ActivityDockProps {
  jobs: ActiveImportJob[]
  hasActive: boolean
  /** True when 3+ consecutive poll failures indicate the backend is unreachable. */
  connectionLost: boolean
  backgroundJobs: BackgroundJob[]
  hasActiveJobs: boolean
  onOpenJob: (jobId: string) => void
  onDismissJob: (jobId: string) => void
  onCancelJob: (jobId: string) => void
  onRefresh: () => void
}

export function ActivityDock({
  jobs,
  hasActive: _hasActive,
  connectionLost,
  backgroundJobs,
  hasActiveJobs: _hasActiveJobs,
  onOpenJob,
  onDismissJob,
  onCancelJob,
  onRefresh,
}: ActivityDockProps) {
  const [expanded, setExpanded] = useState(false)
  const [cleaning, setCleaning] = useState(false)

  useEffect(() => {
    if (!expanded) return
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setExpanded(false)
    }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [expanded])

  const hasAnything = jobs.length > 0 || backgroundJobs.length > 0
  if (!hasAnything) return null

  const activeImportCount = jobs.filter(
    (j) =>
      j.status === 'uploading' ||
      j.status === 'active' ||
      j.status === 'running' ||
      j.runningGroups > 0,
  ).length
  const activeJobCount = backgroundJobs.filter(
    (j) => j.status === 'queued' || j.status === 'running',
  ).length
  const totalActiveCount = activeImportCount + activeJobCount
  const terminalCount =
    jobs.filter(
      (j) =>
        j.status === 'completed' ||
        j.status === 'failed' ||
        j.status === 'cancelled' ||
        j.status === 'broken',
    ).length +
    backgroundJobs.filter((j) => j.status === 'completed' || j.status === 'failed').length

  const handleClearHistory = async () => {
    setCleaning(true)
    try {
      await importApi.cleanup()
      onRefresh()
    } finally {
      setCleaning(false)
    }
  }

  if (!expanded) {
    return (
      <button
        onClick={() => setExpanded(true)}
        className="fixed bottom-6 right-6 z-30
          flex items-center gap-2 py-2 px-3.5
          bg-card/95 backdrop-blur-sm
          border border-border/40 rounded-full
          shadow-lg shadow-black/40
          transition-all duration-200
          hover:bg-secondary hover:border-border/60
          hover:shadow-xl hover:shadow-black/50
          hover:-translate-y-px"
        title={
          connectionLost
            ? 'Connection lost — backend unreachable'
            : totalActiveCount > 0
              ? `${totalActiveCount} active task${totalActiveCount !== 1 ? 's' : ''}`
              : 'Activity'
        }
      >
        {connectionLost ? (
          <WifiOff className="h-4 w-4 text-amber-500/80" />
        ) : totalActiveCount > 0 ? (
          <Loader2 className="h-4 w-4 text-primary animate-spin" />
        ) : (
          <Package className="h-4 w-4 text-primary" />
        )}
        <span className="text-[12px] font-medium text-muted-foreground">Activity</span>
        {connectionLost && <span className="text-[10px] text-amber-500/70">Offline</span>}
        {!connectionLost && totalActiveCount > 0 && (
          <span
            className="min-w-[18px] h-[18px] flex items-center justify-center
            rounded-full bg-primary text-primary-foreground
            text-[10px] font-bold tabular-nums leading-none px-1"
          >
            {totalActiveCount}
          </span>
        )}
      </button>
    )
  }

  return (
    <>
      {/* Click-away overlay */}
      <div className="fixed inset-0 z-20" onClick={() => setExpanded(false)} />

      <div className="fixed bottom-6 right-6 z-30">
        <div
          className="w-[320px] flex flex-col bg-card rounded-xl border border-border/30
            shadow-2xl shadow-black/60 overflow-hidden"
          style={{ maxHeight: 'min(520px, 65vh)' }}
        >
          {/* Amber stripe */}
          <div className="h-0.5 shrink-0 bg-gradient-to-r from-transparent to-primary/70" />

          {/* Header */}
          <div className="px-3.5 pt-2.5 shrink-0">
            <div className="flex items-center justify-between">
              <div className="flex flex-col">
                <div className="flex items-center gap-2">
                  <span className="font-display text-[13px] font-medium tracking-[0.06em] text-foreground leading-none">
                    Activity
                  </span>
                  {totalActiveCount > 0 && (
                    <span className="inline-flex items-center px-1.5 py-px rounded-full bg-primary/15 text-[10px] font-medium text-primary tabular-nums">
                      {totalActiveCount} active
                    </span>
                  )}
                  {connectionLost && (
                    <span className="inline-flex items-center gap-1 text-[10px] text-amber-500/70">
                      <WifiOff className="h-3 w-3" />
                      Connection lost
                    </span>
                  )}
                </div>
                <div className="mt-[3px] h-px w-7 bg-gradient-to-r from-primary to-transparent" />
              </div>
              <div className="flex items-center gap-0.5">
                {terminalCount > 0 && (
                  <button
                    onClick={handleClearHistory}
                    disabled={cleaning}
                    className="h-7 w-7 rounded flex items-center justify-center
                      text-muted-foreground hover:text-destructive hover:bg-destructive/10
                      transition-colors disabled:opacity-30"
                    title="Clear completed"
                  >
                    {cleaning ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Trash2 className="h-3.5 w-3.5" />
                    )}
                  </button>
                )}
                <button
                  onClick={() => setExpanded(false)}
                  className="h-7 w-7 rounded flex items-center justify-center
                    text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors"
                  title="Collapse"
                >
                  <ChevronDown className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
          </div>

          {/* Divider */}
          <div className="mx-3.5 mt-2 h-px bg-border/40 shrink-0" />

          {/* Scrollable job list */}
          <div className="flex-1 min-h-0 overflow-y-auto py-2 px-2 space-y-1.5">
            {/* Import jobs */}
            {jobs.map((job) => (
              <ImportJobCard
                key={job.jobId}
                job={job}
                onOpen={() => onOpenJob(job.jobId)}
                onDismiss={() => onDismissJob(job.jobId)}
                onCancel={() => onCancelJob(job.jobId)}
              />
            ))}

            {/* Section divider — only when both import and background jobs exist */}
            {jobs.length > 0 && backgroundJobs.length > 0 && (
              <div className="flex items-center gap-2 pt-1.5 pb-0.5">
                <div className="h-px flex-1 bg-border/30" />
                <span className="text-[10px] font-semibold uppercase tracking-[0.1em] text-muted-foreground/40 shrink-0">
                  Jobs
                </span>
                <div className="h-px flex-1 bg-border/30" />
              </div>
            )}

            {/* Background jobs */}
            {backgroundJobs.map((job) => (
              <BackgroundJobCard key={job.id} job={job} />
            ))}
          </div>

          {/* Footer */}
          <div
            className="px-3.5 py-[7px] border-t border-border/30 shrink-0 flex items-center justify-between"
            style={{ background: 'hsl(var(--popover))' }}
          >
            <span className="text-[10.5px] text-muted-foreground/50 italic">
              Click imports to open dialog
            </span>
            <span className="text-[10.5px] text-muted-foreground/40 tabular-nums">
              {jobs.length + backgroundJobs.length} jobs
            </span>
          </div>
        </div>
      </div>
    </>
  )
}

/* ─── Sub-components ─────────────────────────────────────────────── */

function ImportJobCard({
  job,
  onOpen,
  onDismiss,
  onCancel,
}: {
  job: ActiveImportJob
  onOpen: () => void
  onDismiss: () => void
  onCancel: () => void
}) {
  const [confirmingCancel, setConfirmingCancel] = useState(false)

  const isTerminal =
    job.status === 'completed' ||
    job.status === 'failed' ||
    job.status === 'cancelled' ||
    job.status === 'expired' ||
    job.status === 'broken'
  // Completed imports require review; broken/failed require cancel for cleanup
  const canDismiss =
    isTerminal && job.status !== 'completed' && job.status !== 'broken' && job.status !== 'failed'
  const canCancel =
    job.status === 'uploading' ||
    job.status === 'staging' ||
    job.status === 'active' ||
    job.status === 'broken' ||
    job.status === 'failed'
  const progressRatio = job.totalFiles > 0 ? job.processedFiles / job.totalFiles : 0

  const handleCancelClick = (e: React.MouseEvent) => {
    e.stopPropagation()
    if (job.processedFiles > 0) {
      setConfirmingCancel(true)
    } else {
      onCancel()
    }
  }

  return (
    <div
      className={`group/job rounded-md border transition-colors cursor-pointer ${
        isTerminal
          ? 'border-border/15 bg-muted/10 opacity-75 hover:opacity-100'
          : 'border-border/30 bg-secondary/20 hover:bg-secondary/40 hover:border-border/50'
      }`}
      onClick={onOpen}
    >
      <div className="px-2.5 py-2">
        {/* Top row */}
        <div className="flex items-start gap-[7px]">
          <ImportStatusIcon status={job.status} />
          <span
            className={`w-0 flex-grow min-w-0 text-[12px] font-medium truncate leading-tight ${
              isTerminal ? 'text-muted-foreground' : 'text-foreground'
            }`}
            title={job.label}
          >
            {job.label}
            {!isTerminal && (
              <span className="ml-1.5 text-muted-foreground/25 text-[13px] transition-all group-hover/job:text-primary/60 group-hover/job:ml-2">
                ›
              </span>
            )}
          </span>
          {canDismiss && !confirmingCancel && (
            <button
              onClick={(e) => {
                e.stopPropagation()
                onDismiss()
              }}
              className="opacity-0 group-hover/job:opacity-100 shrink-0
                h-5 w-5 rounded flex items-center justify-center
                text-muted-foreground/30 hover:text-foreground hover:bg-secondary transition-all"
              title="Dismiss"
            >
              <X className="h-3 w-3" />
            </button>
          )}
          {canCancel && !confirmingCancel && (
            <button
              onClick={handleCancelClick}
              className={`shrink-0 h-5 w-5 rounded flex items-center justify-center
                text-muted-foreground/30 hover:text-destructive hover:bg-destructive/10 transition-all
                ${job.status === 'failed' || job.status === 'broken' ? '' : 'opacity-0 group-hover/job:opacity-100'}`}
              title="Cancel"
            >
              <X className="h-3 w-3" />
            </button>
          )}
          {confirmingCancel && (
            <div className="flex items-center gap-1 shrink-0" onClick={(e) => e.stopPropagation()}>
              <span className="text-[10px] text-destructive/80">Delete imported?</span>
              <button
                onClick={() => {
                  onCancel()
                  setConfirmingCancel(false)
                }}
                className="text-[10px] px-1.5 py-0.5 rounded bg-destructive/15 text-destructive hover:bg-destructive/25 transition-colors"
              >
                Yes
              </button>
              <button
                onClick={() => setConfirmingCancel(false)}
                className="text-[10px] px-1.5 py-0.5 rounded bg-secondary text-muted-foreground hover:bg-secondary/80 transition-colors"
              >
                No
              </button>
            </div>
          )}
        </div>

        {/* Progress bar */}
        <div className="flex items-center gap-2 mt-[7px]">
          <div className="flex-1 h-[3px] rounded-full bg-border/30 overflow-hidden">
            <div
              className={`h-full rounded-full transition-all duration-700 ease-out ${
                job.status === 'failed'
                  ? 'bg-destructive/55'
                  : isTerminal
                    ? 'bg-primary/45'
                    : 'bg-primary/70'
              }`}
              style={{ width: `${Math.round(progressRatio * 100)}%` }}
            />
          </div>
          {job.totalFiles > 0 && (
            <span className="text-[10px] text-muted-foreground/55 tabular-nums shrink-0">
              {job.processedFiles}/{job.totalFiles}
            </span>
          )}
        </div>

        {/* Status summary */}
        <div className="mt-1 text-[10px] text-muted-foreground/45 leading-tight">
          <ImportStatusText job={job} />
        </div>
      </div>
    </div>
  )
}

function BackgroundJobCard({ job }: { job: BackgroundJob }) {
  const [expanded, setExpanded] = useState(false)
  const isTerminal = job.status === 'completed' || job.status === 'failed'
  const pct = job.progress_pct ?? 0

  return (
    <div
      className={`group/job rounded-md border transition-colors cursor-pointer ${
        isTerminal
          ? `border-border/15 bg-muted/10 ${expanded ? 'opacity-100' : 'opacity-75 hover:opacity-100'}`
          : 'border-border/30 bg-secondary/20 hover:bg-secondary/40'
      } ${expanded && isTerminal && job.status === 'failed' ? 'border-destructive/15 bg-destructive/[0.03]' : ''}`}
      onClick={() => isTerminal && setExpanded(!expanded)}
    >
      <div className="px-2.5 py-2">
        <div className="flex items-start gap-[7px]">
          <JobStatusIcon status={job.status} />
          <span
            className={`flex-1 text-[12px] font-medium truncate leading-tight ${
              isTerminal && !expanded ? 'text-muted-foreground' : 'text-foreground'
            }`}
          >
            {job.name}
          </span>
          {job.progress_pct != null && !isTerminal && (
            <span className="text-[10px] text-muted-foreground/55 tabular-nums shrink-0">
              {pct}%
            </span>
          )}
          {expanded && (
            <ChevronDown className="h-3 w-3 text-muted-foreground/40 shrink-0 mt-0.5 rotate-180" />
          )}
        </div>

        {/* Progress bar */}
        {(job.status === 'running' || job.status === 'queued' || isTerminal) && (
          <div className="flex items-center gap-2 mt-[7px]">
            <div className="flex-1 h-[3px] rounded-full bg-border/30 overflow-hidden">
              {job.status === 'queued' ? (
                <div className="h-full w-full bg-muted-foreground/15 animate-pulse" />
              ) : (
                <div
                  className={`h-full rounded-full transition-all duration-700 ease-out ${
                    job.status === 'failed'
                      ? 'bg-destructive/55'
                      : isTerminal
                        ? 'bg-primary/45'
                        : 'bg-primary/70'
                  }`}
                  style={{ width: `${isTerminal && job.status !== 'failed' ? 100 : pct}%` }}
                />
              )}
            </div>
          </div>
        )}

        {/* Status text */}
        <div className="mt-1 text-[10px] text-muted-foreground/45 leading-tight">
          {job.status === 'queued' && <span>Queued</span>}
          {job.status === 'running' && <span>{job.progress ?? 'Processing...'}</span>}
          {job.status === 'completed' && <span>{formatResult(job.result)}</span>}
          {job.status === 'failed' && (
            <span className="text-destructive/65">
              {expanded ? 'Failed' : (job.error ?? 'Failed')}
            </span>
          )}
        </div>

        {/* Inline expansion for terminal jobs */}
        {expanded && isTerminal && (
          <div className="mt-1.5 pt-1.5 border-t border-dashed border-border/30">
            {job.status === 'completed' && job.result && (
              <div className="space-y-0.5">
                {Object.entries(job.result).map(([key, val]) => (
                  <div key={key} className="flex justify-between text-[10px]">
                    <span className="text-muted-foreground/35 font-medium uppercase tracking-[0.08em]">
                      {key.replace(/_/g, ' ')}
                    </span>
                    <span className="text-muted-foreground/55 tabular-nums">{String(val)}</span>
                  </div>
                ))}
              </div>
            )}
            {job.status === 'failed' && job.error && (
              <div className="flex justify-between text-[10px] gap-4">
                <span className="text-muted-foreground/35 font-medium uppercase tracking-[0.08em] shrink-0">
                  Error
                </span>
                <span className="text-destructive/65 text-right">{job.error}</span>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

/* ─── Status icons & helpers ─────────────────────────────────────── */

function ImportStatusIcon({ status }: { status: ActiveImportJob['status'] }) {
  switch (status) {
    case 'uploading':
      return <Upload className="h-3.5 w-3.5 text-primary animate-pulse shrink-0 mt-0.5" />
    case 'running':
    case 'active':
      return <Loader2 className="h-3.5 w-3.5 text-primary animate-spin shrink-0 mt-0.5" />
    case 'completed':
      return <Check className="h-3.5 w-3.5 text-primary/60 shrink-0 mt-0.5" />
    case 'failed':
      return <AlertCircle className="h-3.5 w-3.5 text-destructive/70 shrink-0 mt-0.5" />
    case 'cancelled':
      return <Ban className="h-3.5 w-3.5 text-muted-foreground/40 shrink-0 mt-0.5" />
    case 'broken':
      return <AlertTriangle className="h-3.5 w-3.5 text-amber-500 shrink-0 mt-0.5" />
    case 'expired':
    case 'staging':
    default:
      return <Clock className="h-3.5 w-3.5 text-muted-foreground/50 shrink-0 mt-0.5" />
  }
}

function JobStatusIcon({ status }: { status: BackgroundJob['status'] }) {
  switch (status) {
    case 'running':
      return <Cog className="h-3.5 w-3.5 text-primary animate-spin shrink-0 mt-0.5" />
    case 'completed':
      return <Check className="h-3.5 w-3.5 text-primary/60 shrink-0 mt-0.5" />
    case 'failed':
      return <AlertCircle className="h-3.5 w-3.5 text-destructive/70 shrink-0 mt-0.5" />
    case 'queued':
    default:
      return <Clock className="h-3.5 w-3.5 text-muted-foreground/50 shrink-0 mt-0.5" />
  }
}

function ImportStatusText({ job }: { job: ActiveImportJob }) {
  switch (job.status) {
    case 'uploading':
      return (
        <span>
          {job.totalFiles > 0
            ? `Uploading ${job.processedFiles} of ${job.totalFiles} file${job.totalFiles !== 1 ? 's' : ''}`
            : 'Uploading…'}
        </span>
      )
    case 'staging':
      return (
        <span>
          {job.totalFiles > 0
            ? `${job.totalFiles} image${job.totalFiles !== 1 ? 's' : ''} ready to review`
            : 'Ready to review'}
        </span>
      )
    case 'running':
    case 'active':
      return (
        <span>
          {job.processedFiles > 0
            ? `${job.processedFiles} of ${job.totalFiles} images processed`
            : 'Processing…'}
        </span>
      )
    case 'completed':
      return <span className="text-amber-600 dark:text-amber-400 font-medium">Review import ›</span>
    case 'failed':
      return (
        <span className="text-destructive/65">
          {job.failedGroups} group{job.failedGroups !== 1 ? 's' : ''} failed
          {job.processedFiles > 0 ? `, ${job.processedFiles} images processed` : ''}
        </span>
      )
    case 'cancelled':
      return <span>Cancelled</span>
    case 'expired':
      return <span>Expired</span>
    case 'broken':
      return (
        <span className="text-amber-600 dark:text-amber-400">
          Interrupted — server was restarted
        </span>
      )
    default:
      return null
  }
}

function formatResult(result: Record<string, unknown> | null): string {
  if (!result) return 'Done'
  if ('succeeded' in result && 'failed' in result) {
    const failed = result.failed as number
    return failed > 0
      ? `${result.succeeded} succeeded, ${failed} failed`
      : `${result.succeeded} images processed`
  }
  if ('tags_created' in result) return `${result.tags_created} tags created`
  return 'Done'
}
