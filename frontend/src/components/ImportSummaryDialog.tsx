import { useState, useEffect } from 'react'
import { AlertCircle, AlertTriangle, Loader2, X } from 'lucide-react'
import { importApi } from '@/lib/api'
import type { ImportJobResponse } from '@/types'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'

interface ImportSummaryDialogProps {
  jobId: string | null
  open: boolean
  onClose: () => void
  onCancel: (jobId: string) => void
}

export function ImportSummaryDialog({ jobId, open, onClose, onCancel }: ImportSummaryDialogProps) {
  const [jobDetails, setJobDetails] = useState<ImportJobResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [fetchError, setFetchError] = useState<string | null>(null)

  useEffect(() => {
    if (!open || !jobId) {
      setJobDetails(null)
      setFetchError(null)
      return
    }

    setLoading(true)
    setFetchError(null)
    importApi
      .status(jobId)
      .then((data) => {
        setJobDetails(data)
      })
      .catch(() => {
        setFetchError('Could not load details')
      })
      .finally(() => {
        setLoading(false)
      })
  }, [open, jobId])

  const handleCancel = () => {
    if (jobId) {
      onCancel(jobId)
    }
    onClose()
  }

  const status = jobDetails?.status ?? null

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-lg overflow-hidden p-0 gap-0">
        {/* Colored stripe at top */}
        <div
          className={`h-0.5 ${
            status === 'failed'
              ? 'bg-gradient-to-r from-destructive/80 via-destructive/40 to-transparent'
              : 'bg-gradient-to-r from-amber-500/80 via-amber-500/40 to-transparent'
          }`}
        />

        {/* Header */}
        <div className="flex items-start justify-between px-5 pt-5 pb-3">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2.5 text-base font-semibold text-foreground">
              {status === 'failed' ? (
                <AlertCircle className="h-5 w-5 text-destructive shrink-0" />
              ) : (
                <AlertTriangle className="h-5 w-5 text-amber-500 shrink-0" />
              )}
              Import{' '}
              {status === 'failed' ? (
                <span className="text-destructive">Failed</span>
              ) : (
                <span className="text-amber-500">Interrupted</span>
              )}
            </DialogTitle>
          </DialogHeader>
          <button
            onClick={onClose}
            className="h-7 w-7 rounded flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors shrink-0"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>

        {/* Rule */}
        <div
          className={`mx-5 h-px ${
            status === 'failed'
              ? 'bg-gradient-to-r from-destructive/40 via-destructive/15 to-transparent'
              : 'bg-gradient-to-r from-amber-500/40 via-amber-500/15 to-transparent'
          }`}
        />

        {/* Body */}
        <div className="px-5 py-4 space-y-4">
          {loading && (
            <div className="flex items-center justify-center py-6">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          )}

          {!loading && fetchError && (
            <div className="flex items-center gap-2 text-sm text-destructive bg-destructive/10 border border-destructive/30 rounded-lg px-3 py-2">
              <AlertCircle className="h-4 w-4 shrink-0" />
              {fetchError}
            </div>
          )}

          {!loading && jobDetails && (
            <>
              {/* Source label */}
              {jobDetails.source_label && (
                <div className="flex items-baseline gap-2">
                  <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground/50 shrink-0">
                    Source
                  </span>
                  <span className="text-sm text-foreground truncate">
                    {jobDetails.source_label}
                  </span>
                </div>
              )}

              {/* Top-level error message */}
              {jobDetails.error_message && (
                <div
                  className={`rounded-md border px-3 py-2 text-sm ${
                    status === 'failed'
                      ? 'border-destructive/30 bg-destructive/[0.06] text-destructive/80'
                      : 'border-amber-500/30 bg-amber-500/[0.06] text-amber-600 dark:text-amber-400'
                  }`}
                >
                  {jobDetails.error_message}
                </div>
              )}

              {/* Groups table */}
              {jobDetails.groups.length > 0 && (
                <div className="space-y-1.5">
                  <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground/50">
                    Groups
                  </span>
                  <div className="rounded-md border border-border/30 overflow-hidden">
                    <table className="w-full text-[12px]">
                      <thead>
                        <tr className="border-b border-border/20 bg-muted/20">
                          <th className="text-left px-3 py-1.5 font-medium text-muted-foreground/60 w-full">
                            Name
                          </th>
                          <th className="text-right px-3 py-1.5 font-medium text-muted-foreground/60 whitespace-nowrap">
                            OK
                          </th>
                          <th className="text-right px-3 py-1.5 font-medium text-muted-foreground/60 whitespace-nowrap">
                            Failed
                          </th>
                          <th className="text-right px-3 py-1.5 font-medium text-muted-foreground/60 whitespace-nowrap">
                            Status
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {jobDetails.groups.map((group, i) => (
                          <tr
                            key={group.group_job_id || i}
                            className="border-b border-border/15 last:border-0"
                          >
                            <td className="px-3 py-1.5 text-muted-foreground truncate max-w-[160px]">
                              {group.group_name}
                            </td>
                            <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground/60">
                              {group.processed_files}
                            </td>
                            <td className="px-3 py-1.5 text-right tabular-nums">
                              {group.failed_files > 0 ? (
                                <span className="text-destructive/70">{group.failed_files}</span>
                              ) : (
                                <span className="text-muted-foreground/40">0</span>
                              )}
                            </td>
                            <td className="px-3 py-1.5 text-right">
                              <GroupStatusBadge status={group.status} />
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {/* Per-image file errors */}
              {(() => {
                const allFileErrors = jobDetails.groups.flatMap((g) =>
                  (g.file_errors ?? []).map((e) => ({ ...e, groupName: g.group_name })),
                )
                if (allFileErrors.length === 0) return null
                return (
                  <div className="space-y-1.5">
                    <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground/50">
                      File Errors
                    </span>
                    <div className="rounded-md border border-border/30 overflow-hidden max-h-[160px] overflow-y-auto">
                      {allFileErrors.map((err, i) => (
                        <div
                          key={i}
                          className="flex items-start gap-2 px-3 py-1.5 border-b border-border/15 last:border-0 text-[11px]"
                        >
                          <AlertCircle className="h-3 w-3 text-destructive/60 shrink-0 mt-0.5" />
                          <span className="text-muted-foreground/70 font-medium truncate shrink-0 max-w-[120px]">
                            {err.filename}
                          </span>
                          <span className="text-muted-foreground/50 flex-1 min-w-0">
                            {err.reason}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )
              })()}
            </>
          )}
        </div>

        {/* Footer */}
        <div className="px-5 py-3.5 border-t border-border/30 flex items-center justify-between gap-3 bg-muted/5">
          <button
            onClick={handleCancel}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm rounded border border-destructive/40 bg-destructive/[0.06] text-destructive/80 hover:bg-destructive/10 hover:text-destructive transition-colors"
          >
            Cancel &amp; Clean Up
          </button>
          <button
            onClick={onClose}
            className="px-3.5 py-1.5 text-sm rounded border border-border/40 bg-secondary/50 text-muted-foreground hover:bg-secondary hover:text-foreground transition-colors"
          >
            Close
          </button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

/* ─── Sub-components ──────────────────────────────────────────────── */

function GroupStatusBadge({ status }: { status: string }) {
  switch (status) {
    case 'completed':
      return <span className="text-primary/60 font-medium">Done</span>
    case 'failed':
      return <span className="text-destructive/70 font-medium">Failed</span>
    case 'running':
      return <span className="text-primary/70 font-medium">Running</span>
    case 'pending':
      return <span className="text-muted-foreground/40">Pending</span>
    case 'cancelled':
      return <span className="text-muted-foreground/50">Cancelled</span>
    default:
      return <span className="text-muted-foreground/40">{status}</span>
  }
}
