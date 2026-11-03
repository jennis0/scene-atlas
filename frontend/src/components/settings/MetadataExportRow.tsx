/**
 * Settings → Library → Export metadata (design/export-backup-move.md §4). The desktop app
 * asks where to save it and the backend writes it there; a server writes it to its exports
 * folder and the browser downloads it when the job is done.
 */

import { useEffect, useRef, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { FileDown, Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { getMetadataExportUrl } from '@/lib/api'
import { libraryApi } from '@/lib/api/libraryApi'
import { getApiErrorMessage } from '@/lib/getErrorMessage'
import { saveUrl } from '@/lib/download'
import { useJobPolling } from '@/hooks/useJobPolling'

/** The name the desktop save dialog suggests */
function suggestedExportName(now = new Date()): string {
  return `scene-atlas-metadata-${now.toISOString().slice(0, 10)}.jsonl.gz`
}

function resultText(result: Record<string, unknown> | null, key: string): string | null {
  const value = result?.[key]
  return typeof value === 'string' ? value : null
}

export function MetadataExportRow() {
  const job = useJobPolling()
  const desktop = typeof window.electronAPI?.chooseExportFile === 'function'
  const downloaded = useRef<string | null>(null)
  const [cancelled, setCancelled] = useState(false)

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
    onError: (err) => toast.error(getApiErrorMessage(err, 'Could not start the export')),
  })

  const name = resultText(job.result, 'name')
  const path = resultText(job.result, 'path')

  // Server: hand the finished file to the browser, once
  useEffect(() => {
    if (!desktop && job.isComplete && name && downloaded.current !== name) {
      downloaded.current = name
      saveUrl(getMetadataExportUrl(name), name)
    }
  }, [desktop, job.isComplete, name])

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
        cancelled={cancelled}
        savedTo={desktop ? path : null}
        downloadName={desktop ? null : name}
        onStart={() => start.mutate()}
      />
    </div>
  )
}

function ExportStatus({
  job,
  starting,
  cancelled,
  savedTo,
  downloadName,
  onStart,
}: {
  job: ReturnType<typeof useJobPolling>
  starting: boolean
  cancelled: boolean
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
  const button = (
    <Button
      size="sm"
      variant="outline"
      onClick={onStart}
      disabled={starting}
      className="gap-1.5 h-8 shrink-0"
    >
      {starting ? (
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
      ) : (
        <FileDown className="h-3.5 w-3.5" />
      )}
      Export metadata
    </Button>
  )
  if (job.isComplete && !cancelled) {
    return (
      <div className="flex items-center gap-3 shrink-0">
        {savedTo && (
          <span className="text-sm text-success" title={savedTo}>
            Saved
          </span>
        )}
        {downloadName && (
          <a className="text-sm underline" href={getMetadataExportUrl(downloadName)} download>
            Download again
          </a>
        )}
        {button}
      </div>
    )
  }
  if (job.isFailed) {
    return (
      <div className="flex items-center gap-3 shrink-0">
        <span className="text-sm text-destructive" title={job.error ?? undefined}>
          Failed
        </span>
        {button}
      </div>
    )
  }
  return button
}
