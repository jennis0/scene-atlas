/**
 * The Library tab of the library/settings dialog: what's in the library and how much
 * space it takes, export, and the two destructive resets (each with its own confirm).
 */

import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, Loader2, RotateCcw, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { getLibraryExportUrl, systemApi } from '@/lib/api'
import { getApiErrorMessage } from '@/lib/getErrorMessage'
import { QUERY_KEYS, invalidateTagQueries } from '@/lib/queryKeys'
import { useJobPolling } from '@/hooks/useJobPolling'
import { useStorageDirs } from '@/hooks/useStorageDirs'
import { LinkedFolderSection } from './LinkedFolderSection'
import { downloadFile } from '@/lib/download'
import { formatBytes } from '@/lib/format'

interface SystemInfo {
  storage_path: string
  mode: 'app' | 'server'
  storage: {
    images_bytes: number
    vectors_bytes: number
    metadata_bytes: number
    total_bytes: number
  }
  library: {
    image_count: number
    group_count: number
  }
}

export function LibraryTab({ open }: { open: boolean }) {
  return (
    <div className="px-5 pb-5 pt-4 space-y-5">
      <LibraryOverview open={open} />
      <LinkedFolderSection open={open} />
      <div className="border-t border-border/50" />
      <ExportLibraryButton />
      <section className="rounded-md border border-destructive/15 bg-destructive/[0.03] p-3 space-y-2.5">
        <DeleteLibraryRow />
        <div className="border-t border-destructive/10" />
        <ResetTagsRow />
      </section>
    </div>
  )
}

// What's in the library

function LibraryOverview({ open }: { open: boolean }) {
  const isElectron = typeof window !== 'undefined' && !!window.electronAPI
  const { dirs } = useStorageDirs(open)
  const {
    data: info,
    isLoading,
    isError,
  } = useQuery({
    queryKey: QUERY_KEYS.systemInfo,
    queryFn: () => systemApi.getInfo<SystemInfo>(),
    staleTime: 30_000,
    enabled: open,
  })

  return (
    <>
      {isError ? (
        <p className="text-sm text-muted-foreground italic py-2">
          Could not load library information.
        </p>
      ) : (
        <div className="flex gap-2">
          <StatCard
            label="Images"
            value={info?.library.image_count.toLocaleString() ?? '—'}
            loading={isLoading}
          />
          <StatCard
            label="Groups"
            value={info?.library.group_count.toLocaleString() ?? '—'}
            loading={isLoading}
          />
          <StatCard
            label="Storage"
            value={info ? formatBytes(info.storage.total_bytes) : '—'}
            loading={isLoading}
          />
        </div>
      )}

      {!isError && info && <StorageBar storage={info.storage} />}
      {!isError && isLoading && <StorageBarShimmer />}

      {isElectron && (
        <div className="space-y-1">
          <p className="section-label">Storage</p>
          <div className="space-y-0.5">
            <p className="text-xs text-muted-foreground">
              Search data: <span className="font-mono">{dirs?.appData ?? '—'}</span>
            </p>
            <p className="text-xs text-muted-foreground">
              Imported maps: <span className="font-mono">{dirs?.store ?? '—'}</span>
            </p>
          </div>
          <p className="text-xs text-muted-foreground">
            To change, go to Settings → Storage locations.
          </p>
        </div>
      )}
    </>
  )
}

function Shimmer({ className = '' }: { className?: string }) {
  return <div className={`rounded animate-pulse bg-muted ${className}`} />
}

function StatCard({ label, value, loading }: { label: string; value: string; loading?: boolean }) {
  return (
    <div className="flex-1 min-w-0 rounded-md bg-secondary/60 px-3 py-2.5">
      <p className="section-label mb-1">{label}</p>
      {loading ? (
        <Shimmer className="h-5 w-16" />
      ) : (
        <p className="text-lg font-semibold tabular-nums text-foreground leading-none">{value}</p>
      )}
    </div>
  )
}

function StorageBarShimmer() {
  return (
    <div className="space-y-2">
      <Shimmer className="h-2 w-full rounded-full" />
      <div className="flex gap-4">
        <Shimmer className="h-3 w-20" />
        <Shimmer className="h-3 w-20" />
        <Shimmer className="h-3 w-20" />
      </div>
    </div>
  )
}

function StorageBar({ storage }: { storage: SystemInfo['storage'] }) {
  const total = storage.total_bytes || 1
  const segments = [
    { key: 'images', label: 'Images', bytes: storage.images_bytes, color: 'bg-primary' },
    { key: 'vectors', label: 'Vectors', bytes: storage.vectors_bytes, color: 'bg-sky-400' },
    { key: 'metadata', label: 'Metadata', bytes: storage.metadata_bytes, color: 'bg-emerald-400' },
  ]
  const accounted = segments.reduce((s, seg) => s + seg.bytes, 0)
  const other = Math.max(0, storage.total_bytes - accounted)
  if (other > 0) {
    segments.push({ key: 'other', label: 'Other', bytes: other, color: 'bg-muted-foreground/30' })
  }
  const shown = segments.filter((seg) => seg.bytes > 0)

  return (
    <div className="space-y-2">
      <div className="flex h-2 rounded-full overflow-hidden bg-secondary gap-px">
        {shown.map((seg) => (
          <div
            key={seg.key}
            className={`${seg.color} rounded-full transition-all duration-500`}
            style={{ width: `${Math.max((seg.bytes / total) * 100, 2)}%` }}
          />
        ))}
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1">
        {shown.map((seg) => (
          <div key={seg.key} className="flex items-center gap-1.5">
            <div className={`w-2 h-2 rounded-full ${seg.color}`} />
            <span className="text-2xs text-muted-foreground">
              {seg.label}{' '}
              <span className="tabular-nums text-foreground/70 hc:text-foreground">
                {formatBytes(seg.bytes)}
              </span>
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

// Export

function ExportLibraryButton() {
  const [exporting, setExporting] = useState(false)

  const exportLibrary = async () => {
    setExporting(true)
    try {
      await downloadFile(getLibraryExportUrl(), 'scene-atlas-library.zip', { timeout: 300_000 })
    } catch (err) {
      toast.error(getApiErrorMessage(err, 'Library export failed'))
    } finally {
      setExporting(false)
    }
  }

  return (
    <div className="flex items-center gap-2">
      <Button
        size="sm"
        variant="outline"
        onClick={exportLibrary}
        disabled={exporting}
        className="gap-1.5 h-8"
      >
        {exporting ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
        ) : (
          <Download className="h-3.5 w-3.5" />
        )}
        {exporting ? 'Exporting…' : 'Export library'}
      </Button>
    </div>
  )
}

// Destructive resets

function DangerRow({
  title,
  detail,
  children,
}: {
  title: string
  detail: string
  children: React.ReactNode
}) {
  return (
    <div className="flex items-center justify-between">
      <div className="min-w-0">
        <p className="text-sm text-foreground/90 hc:text-foreground">{title}</p>
        <p className="text-xs text-muted-foreground">{detail}</p>
      </div>
      {children}
    </div>
  )
}

function DeleteLibraryRow() {
  const queryClient = useQueryClient()
  const [confirming, setConfirming] = useState(false)
  const purgeJob = useJobPolling()

  useEffect(() => {
    if (purgeJob.isComplete) queryClient.invalidateQueries()
  }, [purgeJob.isComplete, queryClient])

  const deleteMut = useMutation({
    mutationFn: systemApi.deleteLibrary,
    onSuccess: (data) => {
      setConfirming(false)
      purgeJob.track(data.job_id)
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.backgroundJobs })
    },
    onError: (err) => {
      setConfirming(false)
      toast.error(getApiErrorMessage(err, 'Failed to delete library'))
    },
  })

  return (
    <DangerRow title="Delete library" detail="Remove all images, metadata, and vectors">
      <PurgeStatus job={purgeJob} onDelete={() => setConfirming(true)} />
      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title="Delete Library"
        description="This will permanently delete all images, thumbnails, metadata, tags, and vector embeddings. This cannot be undone."
        confirmLabel="Delete Everything"
        confirmVariant="destructive"
        loadingLabel="Starting…"
        onConfirm={() => deleteMut.mutate()}
        isLoading={deleteMut.isPending}
      />
    </DangerRow>
  )
}

/** The delete button, or the purge's progress once one has started. */
function PurgeStatus({
  job,
  onDelete,
}: {
  job: ReturnType<typeof useJobPolling>
  onDelete: () => void
}) {
  if (job.isRunning) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground shrink-0">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        <span>
          {job.progress ?? 'Deleting…'}
          {job.progressPct != null && ` (${job.progressPct}%)`}
        </span>
      </div>
    )
  }
  if (job.isComplete) {
    return <span className="text-sm text-success shrink-0">Done</span>
  }
  if (job.isFailed) {
    return (
      <span className="text-sm text-destructive shrink-0" title={job.error ?? undefined}>
        Failed
      </span>
    )
  }
  return (
    <Button
      size="sm"
      variant="destructive"
      onClick={onDelete}
      className="gap-1.5 h-7 text-xs shrink-0"
    >
      <Trash2 className="h-3 w-3" />
      Delete
    </Button>
  )
}

function ResetTagsRow() {
  const queryClient = useQueryClient()
  const [confirming, setConfirming] = useState(false)

  const resetTagsMut = useMutation({
    mutationFn: systemApi.resetTags,
    onSuccess: () => {
      setConfirming(false)
      invalidateTagQueries(queryClient)
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.systemInfo })
    },
    onError: (err) => {
      setConfirming(false)
      toast.error(getApiErrorMessage(err, 'Failed to reset tags'))
    },
  })

  return (
    <DangerRow title="Reset tags" detail="Clear all tags and restore default categories">
      <Button
        size="sm"
        variant="destructive"
        onClick={() => setConfirming(true)}
        disabled={resetTagsMut.isPending}
        className="gap-1.5 h-7 text-xs shrink-0"
      >
        {resetTagsMut.isPending ? (
          <Loader2 className="h-3 w-3 animate-spin" />
        ) : (
          <RotateCcw className="h-3 w-3" />
        )}
        Reset
      </Button>
      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title="Reset Tags"
        description="This will delete all tags from every image and reset tag categories to their defaults, keeping only the Common tag pack (add genre packs again from Settings). This cannot be undone."
        confirmLabel="Reset Tags"
        confirmVariant="destructive"
        loadingLabel="Resetting…"
        onConfirm={() => resetTagsMut.mutate()}
        isLoading={resetTagsMut.isPending}
      />
    </DangerRow>
  )
}
