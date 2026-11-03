/**
 * Settings → Library → Export metadata (design/export-backup-move.md §4). The desktop app
 * asks where to save it and the backend writes it there; a server writes it to its exports
 * folder and the browser downloads it when the job is done. Reopening Settings picks up an
 * export still running, and on a server offers the newest finished one.
 */

import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FileDown, Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { getMetadataExportUrl } from '@/lib/api'
import { libraryApi } from '@/lib/api/libraryApi'
import { isApp } from '@/lib/appMode'
import { getApiErrorMessage } from '@/lib/getErrorMessage'
import { saveUrl } from '@/lib/download'
import { useJobPolling } from '@/hooks/useJobPolling'

const STATUS_KEY = ['metadataExport'] as const

/** The name the desktop save dialog suggests */
function suggestedExportName(now = new Date()): string {
  return `scene-atlas-metadata-${now.toISOString().slice(0, 10)}.jsonl.gz`
}

function resultText(result: Record<string, unknown> | null, key: string): string | null {
  const value = result?.[key]
  return typeof value === 'string' ? value : null
}

export function MetadataExportRow() {
  const queryClient = useQueryClient()
  const job = useJobPolling()
  // The backend accepts a path only in the desktop app, which is also where the dialog is
  const desktop = isApp && typeof window.electronAPI?.chooseExportFile === 'function'
  const downloaded = useRef<string | null>(null)
  const [cancelled, setCancelled] = useState(false)

  const status = useQuery({ queryKey: STATUS_KEY, queryFn: libraryApi.metadataExportStatus })
  const runningId = status.data?.job_id ?? null
  const { track } = job
  useEffect(() => {
    if (runningId) track(runningId)
  }, [runningId, track])

  const start = useMutation({
    mutationFn: async () => {
      let path: string | undefined
      if (desktop) {
        const picked = await window.electronAPI!.chooseExportFile(suggestedExportName())
        if (!picked) return null
        path = picked
      }
      return libraryApi.startMetadataExport(path)
    },
    onSuccess: (data) => {
      setCancelled(data === null)
      if (data) job.track(data.job_id)
    },
    onError: (err) => {
      toast.error(getApiErrorMessage(err, 'Could not start the export'))
      // Perhaps one is running already (started before Settings was reopened)
      void queryClient.invalidateQueries({ queryKey: STATUS_KEY })
    },
  })

  const finished = job.isComplete ? resultText(job.result, 'name') : null
  const path = job.isComplete ? resultText(job.result, 'path') : null
  const downloadName = desktop ? null : (finished ?? status.data?.latest ?? null)

  // Server: hand the finished file to the browser, once
  useEffect(() => {
    if (!desktop && finished && downloaded.current !== finished) {
      downloaded.current = finished
      saveUrl(getMetadataExportUrl(finished), finished)
    }
  }, [desktop, finished])

  return (
    <div className="flex items-center justify-between gap-3">
      <div className="min-w-0">
        <p className="text-sm text-foreground/90 hc:text-foreground">Export metadata</p>
        <p className="text-xs text-muted-foreground">
          Names, groups, tags, grids and search data, not the image files. Keep it with a copy of
          your images folder.
        </p>
      </div>
      <ExportStatus
        job={job}
        starting={start.isPending}
        savedTo={desktop && !cancelled ? path : null}
        downloadName={downloadName}
        onStart={() => start.mutate()}
      />
    </div>
  )
}

function ExportStatus({
  job,
  starting,
  savedTo,
  downloadName,
  onStart,
}: {
  job: ReturnType<typeof useJobPolling>
  starting: boolean
  savedTo: string | null
  downloadName: string | null
  onStart: () => void
}) {
  if (job.isRunning) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground shrink-0">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        <span>
          {job.progress ?? 'Exporting…'}
          {job.progressPct != null && ` (${job.progressPct}%)`}
        </span>
      </div>
    )
  }
  return (
    <div className="flex items-center gap-3 shrink-0">
      {savedTo && (
        <span className="text-sm text-success" title={savedTo}>
          Saved
        </span>
      )}
      {job.isFailed && (
        <span className="text-sm text-destructive" title={job.error ?? undefined}>
          Failed
        </span>
      )}
      {downloadName && (
        <a className="text-sm underline" href={getMetadataExportUrl(downloadName)} download>
          Download
        </a>
      )}
      <Button
        size="sm"
        variant="outline"
        onClick={onStart}
        disabled={starting}
        className="gap-1.5 h-8"
      >
        {starting ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
        ) : (
          <FileDown className="h-3.5 w-3.5" />
        )}
        Export metadata
      </Button>
    </div>
  )
}
