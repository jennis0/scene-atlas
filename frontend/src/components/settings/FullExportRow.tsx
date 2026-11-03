/**
 * Settings → Library → Export library (design/export-backup-move.md §7): every image file
 * in readable folders, with the metadata that imports them again, so the library is never
 * locked in to Scene Atlas. The desktop app asks for a folder (empty, or an unfinished
 * export to carry on); a server writes into its images folder's `exports/` and says where.
 * A stopped export (a full disk, say) carries on from where it got to.
 */

import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FolderDown, Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { libraryApi } from '@/lib/api/libraryApi'
import { isApp } from '@/lib/appMode'
import { getApiErrorMessage } from '@/lib/getErrorMessage'
import { useJobPolling } from '@/hooks/useJobPolling'
import { useLibraryStatus } from '@/hooks/useLibraryStatus'

const STATUS_KEY = ['fullExport'] as const

interface ExportResult {
  path: string
  images: number
  skipped: number
  problems: string[]
}

function asResult(result: Record<string, unknown> | null): ExportResult | null {
  return result && typeof result.images === 'number' ? (result as unknown as ExportResult) : null
}

export function FullExportRow() {
  const queryClient = useQueryClient()
  const job = useJobPolling()
  const desktop = isApp && typeof window.electronAPI?.chooseExportFolder === 'function'
  const [includeLinked, setIncludeLinked] = useState(true)
  // The folder of the export started last: "Carry on" goes on there
  const [folder, setFolder] = useState<string | null>(null)

  const status = useQuery({ queryKey: STATUS_KEY, queryFn: libraryApi.fullExportStatus })
  const { data: library } = useLibraryStatus()
  const hasLinked = !!library?.linked
  const runningId = status.data?.job_id ?? null
  const { track } = job
  useEffect(() => {
    if (runningId) track(runningId)
  }, [runningId, track])

  const start = useMutation({
    mutationFn: async (resume: boolean) => {
      let path: string | undefined
      if (desktop) {
        const picked = resume && folder ? folder : await window.electronAPI!.chooseExportFolder()
        if (!picked) return null
        path = picked
      }
      return libraryApi.startFullExport({ path, resume, includeLinked })
    },
    onSuccess: (data) => {
      if (!data) return
      setFolder(data.path)
      job.track(data.job_id)
    },
    onError: (err) => {
      toast.error(getApiErrorMessage(err, 'Could not start the export'))
      void queryClient.invalidateQueries({ queryKey: STATUS_KEY })
    },
  })

  const result = job.isComplete ? asResult(job.result) : null
  // A server carries on its newest export; the desktop app the folder it chose
  const canCarryOn = job.isFailed && (desktop ? !!folder : true)

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm text-foreground/90 hc:text-foreground">Export library</p>
          <p className="text-xs text-muted-foreground">
            Every image, in folders named after its groups, with the metadata to import them again.
            The files work without Scene Atlas.
            {!desktop && status.data?.folder && (
              <>
                {' '}
                Written on the server to{' '}
                <span className="font-mono break-all">{status.data.folder}</span>.
              </>
            )}
          </p>
        </div>
        {job.isRunning ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground shrink-0">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            <span>
              {job.progress ?? 'Exporting…'}
              {job.progressPct != null && ` (${job.progressPct}%)`}
            </span>
          </div>
        ) : (
          <div className="flex items-center gap-2 shrink-0">
            {canCarryOn && (
              <Button
                size="sm"
                variant="outline"
                onClick={() => start.mutate(true)}
                disabled={start.isPending}
                className="h-8"
              >
                Carry on
              </Button>
            )}
            <Button
              size="sm"
              variant="outline"
              onClick={() => start.mutate(false)}
              disabled={start.isPending}
              className="gap-1.5 h-8"
            >
              {start.isPending ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <FolderDown className="h-3.5 w-3.5" />
              )}
              {desktop ? 'Export library…' : 'Export library'}
            </Button>
          </div>
        )}
      </div>
      {hasLinked && !job.isRunning && (
        <label className="flex items-center gap-2 text-xs text-muted-foreground">
          <Checkbox
            checked={includeLinked}
            onCheckedChange={(checked) => setIncludeLinked(checked === true)}
          />
          Include the linked library&apos;s images (you have those files already)
        </label>
      )}
      {result && <ExportDone result={result} />}
      {job.isFailed && (
        <p className="text-xs text-destructive" role="alert">
          The export stopped: {job.error ?? 'something went wrong'}.{' '}
          {canCarryOn && 'What it wrote is kept; Carry on picks up from there.'}
        </p>
      )}
    </div>
  )
}

function ExportDone({ result }: { result: ExportResult }) {
  return (
    <div className="text-xs space-y-1" role="status">
      <p className="text-success">
        Exported {result.images.toLocaleString()} images to{' '}
        <span className="font-mono break-all">{result.path}</span>
      </p>
      {result.skipped > 0 && (
        <details className="text-muted-foreground">
          <summary className="cursor-pointer">
            {result.skipped.toLocaleString()} couldn&apos;t be exported
          </summary>
          <ul className="mt-1 ml-4 list-disc space-y-0.5">
            {result.problems.map((p) => (
              <li key={p} className="break-all">
                {p}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  )
}
