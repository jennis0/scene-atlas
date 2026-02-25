import { useState, useEffect } from 'react'
import {
  ChevronLeft,
  ChevronRight,
  Check,
  Loader2,
  AlertCircle,
  Package,
  X,
  Clock,
  Ban,
  Trash2,
  Cog,
} from 'lucide-react'
import { importApi } from '@/lib/api'
import type { BackgroundJob } from '@/types'

interface ActiveImportJob {
  jobId: string
  label: string
  status: 'staging' | 'running' | 'completed' | 'failed' | 'cancelled'
  totalGroups: number
  completedGroups: number
  failedGroups: number
  runningGroups: number
  pendingGroups: number
  totalFiles: number
  createdAt: string
  localOnly: boolean
}

interface ImportTrayProps {
  jobs: ActiveImportJob[]
  hasActive: boolean
  backgroundJobs: BackgroundJob[]
  hasActiveJobs: boolean
  onOpenJob: (jobId: string) => void
  onDismissJob: (jobId: string) => void
  onCancelJob: (jobId: string) => void
  onRefresh: () => void
}

export function ImportTray({
  jobs,
  hasActive,
  backgroundJobs,
  hasActiveJobs,
  onOpenJob,
  onDismissJob,
  onCancelJob,
  onRefresh,
}: ImportTrayProps) {
  const [expanded, setExpanded] = useState(false)
  const [cleaning, setCleaning] = useState(false)

  // Auto-expand when new active jobs appear (imports or background)
  useEffect(() => {
    if (hasActive || hasActiveJobs) setExpanded(true)
  }, [hasActive, hasActiveJobs])

  const handleClearHistory = async () => {
    setCleaning(true)
    try {
      await importApi.cleanup()
      onRefresh()
    } finally {
      setCleaning(false)
    }
  }

  const hasAnything = jobs.length > 0 || backgroundJobs.length > 0
  if (!hasAnything) return null

  const activeImportCount = jobs.filter(
    (j) => j.status === 'staging' || j.status === 'running' || j.pendingGroups > 0,
  ).length
  const activeJobCount = backgroundJobs.filter(
    (j) => j.status === 'queued' || j.status === 'running',
  ).length
  const totalActiveCount = activeImportCount + activeJobCount
  const terminalCount = jobs.filter(
    (j) => j.status === 'completed' || j.status === 'failed' || j.status === 'cancelled',
  ).length

  return (
    <>
      {/* Click-away overlay — closes tray when clicking outside */}
      {expanded && <div className="fixed inset-0 z-20" onClick={() => setExpanded(false)} />}

      {/* Collapsed toggle tab — visible when tray is hidden */}
      {!expanded && (
        <button
          onClick={() => setExpanded(true)}
          className="fixed right-0 top-1/2 -translate-y-1/2 z-30
            flex items-center gap-1.5 pl-2.5 pr-1.5 py-2.5
            bg-card/95 backdrop-blur-sm border border-r-0 border-border/40
            rounded-l-lg shadow-lg shadow-black/40
            text-muted-foreground hover:text-foreground hover:bg-secondary
            transition-all duration-200"
          title={
            totalActiveCount > 0
              ? `${totalActiveCount} active task${totalActiveCount !== 1 ? 's' : ''}`
              : 'Activity tray'
          }
        >
          <Package className="h-4 w-4" />
          {totalActiveCount > 0 && (
            <span
              className="min-w-[18px] h-[18px] flex items-center justify-center
              rounded-full bg-primary text-primary-foreground
              text-[10px] font-semibold tabular-nums leading-none"
            >
              {totalActiveCount}
            </span>
          )}
          <ChevronLeft className="h-3 w-3 opacity-50" />
        </button>
      )}

      {/* Tray panel */}
      <div
        className={`fixed right-0 top-0 h-full z-30
          w-[260px] flex flex-col
          bg-card/98 backdrop-blur-md
          border-l border-border/40
          shadow-2xl shadow-black/60
          transition-transform duration-300 ease-out
          ${expanded ? 'translate-x-0' : 'translate-x-full'}`}
      >
        {/* Top accent stripe */}
        <div className="absolute top-0 inset-x-0 h-0.5 bg-gradient-to-r from-transparent via-primary/40 to-primary/70 pointer-events-none" />

        {/* Header */}
        <div className="flex items-center justify-between px-4 pt-5 pb-3 shrink-0">
          <div className="flex items-center gap-2">
            <Package className="h-4 w-4 text-primary" />
            <span className="font-display text-sm font-semibold text-foreground tracking-wide">
              Activity
            </span>
            {totalActiveCount > 0 && (
              <span
                className="min-w-[18px] h-[18px] flex items-center justify-center
                rounded-full bg-primary/20 text-primary
                text-[10px] font-semibold tabular-nums leading-none"
              >
                {totalActiveCount}
              </span>
            )}
          </div>
          <div className="flex items-center gap-1">
            {terminalCount > 0 && (
              <button
                onClick={handleClearHistory}
                disabled={cleaning}
                className="h-6 w-6 rounded flex items-center justify-center
                  text-muted-foreground/40 hover:text-muted-foreground hover:bg-secondary
                  transition-colors"
                title="Clear completed imports"
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
              className="h-6 w-6 rounded flex items-center justify-center
                text-muted-foreground/60 hover:text-foreground hover:bg-secondary
                transition-colors"
              title="Collapse tray"
            >
              <ChevronRight className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>

        {/* Divider */}
        <div className="h-px bg-gradient-to-r from-primary/30 via-border/40 to-transparent mx-4 shrink-0" />

        {/* Scrollable content */}
        <div className="flex-1 overflow-y-auto py-2 px-3 space-y-1.5">
          {/* Import jobs */}
          {jobs.map((job) => (
            <ImportTrayCard
              key={job.jobId}
              job={job}
              onOpen={() => onOpenJob(job.jobId)}
              onDismiss={() => onDismissJob(job.jobId)}
              onCancel={() => onCancelJob(job.jobId)}
            />
          ))}

          {/* Background jobs section */}
          {backgroundJobs.length > 0 && (
            <>
              {jobs.length > 0 && (
                <div className="flex items-center gap-2 pt-2 pb-1">
                  <div className="h-px flex-1 bg-border/30" />
                  <span className="text-[10px] text-muted-foreground/40 font-medium uppercase tracking-wider shrink-0">
                    Jobs
                  </span>
                  <div className="h-px flex-1 bg-border/30" />
                </div>
              )}
              {backgroundJobs.map((job) => (
                <BackgroundJobCard key={job.id} job={job} />
              ))}
            </>
          )}
        </div>
      </div>
    </>
  )
}

// ── Individual import job card ────────────────────────────────────

function ImportTrayCard({
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
  const isTerminal =
    job.status === 'completed' ||
    job.status === 'failed' ||
    job.status === 'cancelled' ||
    job.status === 'expired'
  const canCancel = job.status === 'staging' || job.status === 'active'
  const effectiveTotal = job.totalGroups > 0 ? job.totalGroups : job.pendingGroups + job.completedGroups + job.failedGroups + job.runningGroups
  const progressRatio = effectiveTotal > 0 ? job.completedGroups / effectiveTotal : 0

  return (
    <div
      className={`group relative rounded-md border transition-colors cursor-pointer
        ${
          isTerminal
            ? 'border-border/20 bg-muted/10 hover:bg-secondary/30'
            : 'border-border/30 bg-secondary/20 hover:bg-secondary/40 hover:border-border/50'
        }`}
      onClick={onOpen}
    >
      {/* Card content */}
      <div className="px-3 py-2.5">
        {/* Top row: label + status icon */}
        <div className="flex items-start gap-2">
          <StatusIcon status={job.status} />
          <span
            className={`flex-1 text-[12px] font-medium truncate leading-tight
            ${isTerminal ? 'text-muted-foreground' : 'text-foreground'}`}
          >
            {job.label}
          </span>
          {isTerminal && (
            <button
              onClick={(e) => {
                e.stopPropagation()
                onDismiss()
              }}
              className="opacity-0 group-hover:opacity-100 shrink-0
                h-5 w-5 rounded flex items-center justify-center
                text-muted-foreground/40 hover:text-foreground hover:bg-secondary
                transition-all"
              title="Dismiss"
            >
              <X className="h-3 w-3" />
            </button>
          )}
          {canCancel && (
            <button
              onClick={(e) => {
                e.stopPropagation()
                onCancel()
              }}
              className="opacity-0 group-hover:opacity-100 shrink-0
                h-5 w-5 rounded flex items-center justify-center
                text-muted-foreground/40 hover:text-destructive hover:bg-secondary
                transition-all"
              title="Cancel import"
            >
              <X className="h-3 w-3" />
            </button>
          )}
        </div>

        {/* Progress section */}
        <div className="mt-2 flex items-center gap-2">
          {/* Progress bar */}
          <div className="flex-1 h-1 rounded-full bg-border/30 overflow-hidden">
            <div
              className={`h-full rounded-full transition-all duration-700 ease-out
                ${
                  job.status === 'failed'
                    ? 'bg-destructive/60'
                    : job.status === 'completed'
                      ? 'bg-primary/50'
                      : 'bg-primary/70'
                }`}
              style={{ width: `${Math.round(progressRatio * 100)}%` }}
            />
          </div>

          {/* Count */}
          <span className="text-[10px] text-muted-foreground/60 tabular-nums shrink-0">
            {job.completedGroups}/{job.totalGroups}
          </span>
        </div>

        {/* Status summary line */}
        <div className="mt-1.5 text-[10px] text-muted-foreground/50 leading-tight">
          {(job.status === 'running' || job.status === 'active') && (
            <span>
              {job.runningGroups > 0 ? `${job.runningGroups} processing` : ''}
              {job.runningGroups > 0 && (job.pendingGroups > 0 || job.completedGroups > 0)
                ? ', '
                : ''}
              {job.completedGroups > 0 ? `${job.completedGroups} imported` : ''}
              {job.completedGroups > 0 && job.pendingGroups > 0 ? ', ' : ''}
              {job.pendingGroups > 0 ? `${job.pendingGroups} pending` : ''}
              {job.runningGroups === 0 && job.pendingGroups === 0 && job.completedGroups === 0
                ? 'Processing…'
                : ''}
            </span>
          )}
          {job.status === 'staging' && (
            <span>
              {job.pendingGroups} group{job.pendingGroups !== 1 ? 's' : ''} ready to review
            </span>
          )}
          {job.status === 'completed' && (
            <span>
              {job.completedGroups} group{job.completedGroups !== 1 ? 's' : ''} imported
            </span>
          )}
          {job.status === 'failed' && (
            <span>
              {job.failedGroups} failed
              {job.completedGroups > 0 ? `, ${job.completedGroups} completed` : ''}
            </span>
          )}
          {job.status === 'cancelled' && <span>Cancelled</span>}
          {job.status === 'expired' && <span>Expired</span>}
        </div>
      </div>
    </div>
  )
}

// ── Background job card ───────────────────────────────────────────

function BackgroundJobCard({ job }: { job: BackgroundJob }) {
  const isTerminal = job.status === 'completed' || job.status === 'failed'
  const pct = job.progress_pct ?? 0

  return (
    <div
      className={`rounded-md border transition-colors
        ${isTerminal ? 'border-border/20 bg-muted/10' : 'border-border/30 bg-secondary/20'}`}
    >
      <div className="px-3 py-2.5">
        {/* Top row: icon + name */}
        <div className="flex items-start gap-2">
          <JobStatusIcon status={job.status} />
          <span
            className={`flex-1 text-[12px] font-medium truncate leading-tight
            ${isTerminal ? 'text-muted-foreground' : 'text-foreground'}`}
          >
            {job.name}
          </span>
          {job.progress_pct != null && !isTerminal && (
            <span className="text-[10px] text-muted-foreground/60 tabular-nums shrink-0">
              {pct}%
            </span>
          )}
        </div>

        {/* Progress bar */}
        {(job.status === 'running' || job.status === 'queued') && (
          <div className="mt-2 h-1 rounded-full bg-border/30 overflow-hidden">
            {job.status === 'queued' ? (
              <div className="h-full w-full bg-muted-foreground/20 animate-pulse" />
            ) : (
              <div
                className="h-full rounded-full bg-primary/70 transition-all duration-700 ease-out"
                style={{ width: `${pct}%` }}
              />
            )}
          </div>
        )}

        {/* Status line */}
        <div className="mt-1.5 text-[10px] text-muted-foreground/50 leading-tight">
          {job.status === 'queued' && <span>Queued</span>}
          {job.status === 'running' && <span>{job.progress ?? 'Processing...'}</span>}
          {job.status === 'completed' && <span>{formatResult(job.result)}</span>}
          {job.status === 'failed' && (
            <span className="text-destructive/70">{job.error ?? 'Failed'}</span>
          )}
        </div>
      </div>
    </div>
  )
}

function formatResult(result: Record<string, unknown> | null): string {
  if (!result) return 'Done'
  // Common result shapes: {total, succeeded, failed} or {total, tags_created, errors}
  if ('succeeded' in result && 'failed' in result) {
    const failed = result.failed as number
    return failed > 0
      ? `${result.succeeded} succeeded, ${failed} failed`
      : `${result.succeeded} images processed`
  }
  if ('tags_created' in result) {
    return `${result.tags_created} tags created`
  }
  return 'Done'
}

// ── Status icon helpers ───────────────────────────────────────────

function StatusIcon({ status }: { status: ActiveImportJob['status'] }) {
  switch (status) {
    case 'running':
      return <Loader2 className="h-3.5 w-3.5 text-primary animate-spin shrink-0 mt-0.5" />
    case 'active':
      return <Loader2 className="h-3.5 w-3.5 text-primary/70 animate-spin shrink-0 mt-0.5" />
    case 'completed':
      return <Check className="h-3.5 w-3.5 text-primary/60 shrink-0 mt-0.5" />
    case 'failed':
      return <AlertCircle className="h-3.5 w-3.5 text-destructive/70 shrink-0 mt-0.5" />
    case 'cancelled':
      return <Ban className="h-3.5 w-3.5 text-muted-foreground/40 shrink-0 mt-0.5" />
    case 'expired':
      return <Clock className="h-3.5 w-3.5 text-muted-foreground/40 shrink-0 mt-0.5" />
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
