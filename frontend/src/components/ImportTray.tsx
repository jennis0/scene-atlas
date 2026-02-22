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
} from 'lucide-react'
import { importApi } from '@/lib/api'

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
  onOpenJob: (jobId: string) => void
  onDismissJob: (jobId: string) => void
  onCancelJob: (jobId: string) => void
  onRefresh: () => void
}

export function ImportTray({
  jobs,
  hasActive,
  onOpenJob,
  onDismissJob,
  onCancelJob,
  onRefresh,
}: ImportTrayProps) {
  const [expanded, setExpanded] = useState(false)
  const [cleaning, setCleaning] = useState(false)

  // Auto-expand when new active jobs appear
  useEffect(() => {
    if (hasActive) setExpanded(true)
  }, [hasActive])

  const handleClearHistory = async () => {
    setCleaning(true)
    try {
      await importApi.cleanup()
      onRefresh()
    } finally {
      setCleaning(false)
    }
  }

  if (jobs.length === 0) return null

  const activeCount = jobs.filter(
    (j) => j.status === 'staging' || j.status === 'running' || j.pendingGroups > 0,
  ).length
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
          title={`${activeCount} active import${activeCount !== 1 ? 's' : ''}`}
        >
          <Package className="h-4 w-4" />
          {activeCount > 0 && (
            <span
              className="min-w-[18px] h-[18px] flex items-center justify-center
              rounded-full bg-primary text-primary-foreground
              text-[10px] font-semibold tabular-nums leading-none"
            >
              {activeCount}
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
        {/* Top amber accent stripe */}
        <div className="absolute top-0 inset-x-0 h-0.5 bg-gradient-to-r from-transparent via-primary/40 to-primary/70 pointer-events-none" />

        {/* Header */}
        <div className="flex items-center justify-between px-4 pt-5 pb-3 shrink-0">
          <div className="flex items-center gap-2">
            <Package className="h-4 w-4 text-primary" />
            <span className="font-display text-sm font-semibold text-foreground tracking-wide">
              Imports
            </span>
            {activeCount > 0 && (
              <span
                className="min-w-[18px] h-[18px] flex items-center justify-center
                rounded-full bg-primary/20 text-primary
                text-[10px] font-semibold tabular-nums leading-none"
              >
                {activeCount}
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

        {/* Job list */}
        <div className="flex-1 overflow-y-auto py-2 px-3 space-y-1.5">
          {jobs.map((job) => (
            <ImportTrayCard
              key={job.jobId}
              job={job}
              onOpen={() => onOpenJob(job.jobId)}
              onDismiss={() => onDismissJob(job.jobId)}
              onCancel={() => onCancelJob(job.jobId)}
            />
          ))}
        </div>
      </div>
    </>
  )
}

// ── Individual job card ───────────────────────────────────────────

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
    job.status === 'completed' || job.status === 'failed' || job.status === 'cancelled'
  const canCancel = job.status === 'staging'
  const progressRatio = job.totalGroups > 0 ? job.completedGroups / job.totalGroups : 0

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
          {job.status === 'running' && (
            <span>
              {job.runningGroups} processing
              {job.pendingGroups > 0 ? `, ${job.pendingGroups} pending` : ''}
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
        </div>
      </div>
    </div>
  )
}

// ── Status icon helper ────────────────────────────────────────────

function StatusIcon({ status }: { status: ActiveImportJob['status'] }) {
  switch (status) {
    case 'running':
      return <Loader2 className="h-3.5 w-3.5 text-primary animate-spin shrink-0 mt-0.5" />
    case 'completed':
      return <Check className="h-3.5 w-3.5 text-primary/60 shrink-0 mt-0.5" />
    case 'failed':
      return <AlertCircle className="h-3.5 w-3.5 text-destructive/70 shrink-0 mt-0.5" />
    case 'cancelled':
      return <Ban className="h-3.5 w-3.5 text-muted-foreground/40 shrink-0 mt-0.5" />
    case 'staging':
    default:
      return <Clock className="h-3.5 w-3.5 text-muted-foreground/50 shrink-0 mt-0.5" />
  }
}
