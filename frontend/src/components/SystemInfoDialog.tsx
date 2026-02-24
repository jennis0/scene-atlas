import { useState, useEffect } from 'react'
import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query'
import {
  FolderOpen,
  FolderInput,
  RotateCcw,
  HardDrive,
  ArrowRight,
  X,
  Trash2,
  Loader2,
  Download,
} from 'lucide-react'
import { Dialog, DialogContent } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { systemApi, getLibraryExportUrl } from '@/lib/api'
import { useJobPolling } from '@/hooks/useJobPolling'

// ── Types ─────────────────────────────────────────────────────────────────────

interface SystemInfo {
  storage_path: string
  mode: 'app' | 'server'
  storage: {
    images_bytes: number
    thumbnails_bytes: number
    qdrant_bytes: number
    total_bytes: number
  }
  library: {
    image_count: number
    group_count: number
  }
}

export interface SystemInfoDialogProps {
  open: boolean
  onClose: () => void
}

type LocationPhase = 'idle' | 'confirming' | 'restarting'

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  const val = bytes / Math.pow(1024, i)
  return `${i === 0 ? Math.round(val) : val.toFixed(1)} ${units[i]}`
}

// ── Sub-components ────────────────────────────────────────────────────────────

function Shimmer({ className = '' }: { className?: string }) {
  return <div className={`rounded animate-pulse bg-zinc-700/40 ${className}`} />
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <p className="text-xs font-semibold text-zinc-500 tracking-wide uppercase mb-2">{children}</p>
  )
}

function DataRow({
  label,
  value,
  highlight = false,
}: {
  label: string
  value: string
  highlight?: boolean
}) {
  return (
    <div className="flex items-center justify-between py-1">
      <span className="text-sm text-zinc-400">{label}</span>
      <span
        className={`text-sm tabular-nums ${
          highlight ? 'text-amber-400 font-medium' : 'text-zinc-300'
        }`}
      >
        {value}
      </span>
    </div>
  )
}

function DataRowSkeleton({ wide = false }: { wide?: boolean }) {
  return (
    <div className="flex items-center justify-between py-1">
      <Shimmer className={`h-3 ${wide ? 'w-24' : 'w-16'}`} />
      <Shimmer className="h-3 w-14" />
    </div>
  )
}

function ErrorNote() {
  return <p className="text-sm text-zinc-500 italic py-1">Could not load system information.</p>
}

// ── Main component ────────────────────────────────────────────────────────────

export function SystemInfoDialog({ open, onClose }: SystemInfoDialogProps) {
  const isElectron = !!window.electronAPI
  const queryClient = useQueryClient()
  const [locationPhase, setLocationPhase] = useState<LocationPhase>('idle')
  const [pendingDir, setPendingDir] = useState<string | null>(null)
  const [dataDir, setDataDir] = useState<string | null>(null)
  const [confirmingDelete, setConfirmingDelete] = useState(false)
  const [confirmingResetTags, setConfirmingResetTags] = useState(false)
  const [exportingLibrary, setExportingLibrary] = useState(false)

  // Library purge job polling
  const purgeJob = useJobPolling()

  // When purge completes, refresh all data
  useEffect(() => {
    if (purgeJob.isComplete) {
      queryClient.invalidateQueries()
    }
  }, [purgeJob.isComplete, queryClient])

  useEffect(() => {
    if (open && window.electronAPI) {
      window.electronAPI.getDataDir().then(setDataDir)
    }
  }, [open])

  const {
    data: info,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ['system-info'],
    queryFn: () => systemApi.getInfo<SystemInfo>(),
    staleTime: 30_000,
    enabled: open,
  })

  const deleteMut = useMutation({
    mutationFn: systemApi.deleteLibrary,
    onSuccess: (data) => {
      setConfirmingDelete(false)
      purgeJob.track(data.job_id)
    },
  })

  const resetTagsMut = useMutation({
    mutationFn: systemApi.resetTags,
    onSuccess: () => {
      setConfirmingResetTags(false)
      queryClient.invalidateQueries({ queryKey: ['tagCategories'] })
      queryClient.invalidateQueries({ queryKey: ['searchFacets'] })
      queryClient.invalidateQueries({ queryKey: ['system-info'] })
    },
  })

  const handleOpenInExplorer = () => window.electronAPI?.openDataDir()

  const handleChooseDir = async () => {
    const chosen = await window.electronAPI?.chooseDataDir()
    if (chosen && chosen !== dataDir) {
      setPendingDir(chosen)
      setLocationPhase('confirming')
    }
  }

  const handleConfirmChange = async () => {
    if (!pendingDir) return
    setLocationPhase('restarting')
    await window.electronAPI?.changeDataDir(pendingDir)
  }

  const handleCancelChange = () => {
    setPendingDir(null)
    setLocationPhase('idle')
  }

  const handleExportLibrary = async () => {
    setExportingLibrary(true)
    try {
      const resp = await fetch(getLibraryExportUrl())
      const blob = await resp.blob()
      const objectUrl = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = objectUrl
      a.download = 'scene-atlas-library.zip'
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(objectUrl)
    } catch (err) {
      console.error('Library export failed', err)
    } finally {
      setExportingLibrary(false)
    }
  }

  const handleOpenChange = (v: boolean) => {
    if (!v) {
      onClose()
      setTimeout(() => {
        setLocationPhase('idle')
        setPendingDir(null)
      }, 200)
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-w-[440px] bg-zinc-900 border-zinc-700/50 p-0 overflow-hidden">
        {/* Header */}
        <div className="flex items-center gap-2 px-4 py-3 border-b border-zinc-800 bg-gradient-to-b from-amber-400/5 to-transparent">
          <HardDrive className="w-3.5 h-3.5 text-amber-400 shrink-0" />
          <h2 className="text-xs font-semibold text-zinc-300 tracking-wide uppercase">System</h2>
          <span className="text-xs text-zinc-600 ml-0.5">· Storage &amp; Library</span>
          <button
            onClick={onClose}
            className="ml-auto rounded-sm p-1 opacity-70 transition-opacity hover:opacity-100 text-zinc-400 hover:text-zinc-100"
          >
            <X className="h-4 w-4" />
            <span className="sr-only">Close</span>
          </button>
        </div>

        {/* Body */}
        <div className="px-4 py-4 space-y-5">
          {/* ── Library Location — Electron only ─────────────── */}
          {isElectron && (
            <section>
              <SectionLabel>Library Location</SectionLabel>

              {locationPhase === 'restarting' ? (
                <div className="flex items-center gap-2.5 py-2">
                  <RotateCcw className="h-3.5 w-3.5 animate-spin shrink-0 text-amber-400" />
                  <span className="text-sm text-zinc-400">Restarting Scene Atlas…</span>
                </div>
              ) : locationPhase === 'confirming' && pendingDir ? (
                <div className="space-y-3">
                  <div className="rounded border border-zinc-700/50 bg-zinc-800/50 p-3 space-y-2.5">
                    <div className="space-y-1">
                      <span className="text-xs text-zinc-600 uppercase tracking-wide">Current</span>
                      <p className="text-sm text-zinc-400 break-all leading-relaxed">
                        {dataDir ?? '—'}
                      </p>
                    </div>
                    <div className="flex items-center gap-2">
                      <ArrowRight className="h-3 w-3 shrink-0 text-amber-400/50" />
                      <div className="h-px flex-1 border-t border-dashed border-zinc-700/50" />
                    </div>
                    <div className="space-y-1">
                      <span className="text-xs text-amber-400/70 uppercase tracking-wide">New</span>
                      <p className="text-sm text-amber-400 break-all leading-relaxed">
                        {pendingDir}
                      </p>
                    </div>
                  </div>
                  <p className="text-xs text-zinc-500">
                    Scene Atlas will restart to apply the new location.
                  </p>
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={handleCancelChange}
                      className="flex-1 h-8 border-zinc-700 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-300"
                    >
                      Cancel
                    </Button>
                    <Button
                      size="sm"
                      onClick={handleConfirmChange}
                      className="flex-1 h-8 bg-amber-400/10 border border-amber-400/30 text-amber-400 hover:bg-amber-400/20"
                    >
                      Restart &amp; Apply
                    </Button>
                  </div>
                </div>
              ) : (
                <div className="space-y-3">
                  <div className="rounded border border-zinc-700/50 bg-zinc-800/50 px-3 py-2.5 min-h-[2.5rem] flex items-center">
                    {dataDir ? (
                      <p className="text-sm text-zinc-300 break-all leading-relaxed">{dataDir}</p>
                    ) : (
                      <Shimmer className="h-3 w-3/4" />
                    )}
                  </div>
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={handleOpenInExplorer}
                      disabled={!dataDir}
                      className="gap-1.5 h-8 border-zinc-700 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-300"
                    >
                      <FolderOpen className="h-3.5 w-3.5" />
                      Open
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={handleChooseDir}
                      disabled={!dataDir}
                      className="gap-1.5 h-8 border-zinc-700 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-300"
                    >
                      <FolderInput className="h-3.5 w-3.5" />
                      Change Location
                    </Button>
                  </div>
                </div>
              )}
            </section>
          )}

          {/* ── Storage ───────────────────────────────────────── */}
          <section>
            <SectionLabel>Storage</SectionLabel>
            <div className="space-y-0.5">
              {isLoading ? (
                <>
                  {isElectron && (
                    <>
                      <DataRowSkeleton />
                      <DataRowSkeleton />
                      <DataRowSkeleton />
                      <div className="mt-2 pt-2 border-t border-zinc-800">
                        <DataRowSkeleton wide />
                      </div>
                    </>
                  )}
                  {!isElectron && <DataRowSkeleton wide />}
                </>
              ) : isError ? (
                <ErrorNote />
              ) : info ? (
                <>
                  {isElectron && (
                    <>
                      <DataRow label="Images" value={formatBytes(info.storage.images_bytes)} />
                      <DataRow
                        label="Thumbnails"
                        value={formatBytes(info.storage.thumbnails_bytes)}
                      />
                      <DataRow
                        label="Search index"
                        value={formatBytes(info.storage.qdrant_bytes)}
                      />
                      <div className="mt-2 pt-2 border-t border-zinc-800">
                        <DataRow
                          label="Total"
                          value={formatBytes(info.storage.total_bytes)}
                          highlight
                        />
                      </div>
                    </>
                  )}
                  {!isElectron && (
                    <DataRow
                      label="Total"
                      value={formatBytes(info.storage.total_bytes)}
                      highlight
                    />
                  )}
                </>
              ) : null}
            </div>
          </section>

          {/* ── Collection ────────────────────────────────────── */}
          <section className="pb-1">
            <SectionLabel>Collection</SectionLabel>
            <div className="space-y-0.5">
              {isLoading ? (
                <>
                  <DataRowSkeleton />
                  <DataRowSkeleton />
                </>
              ) : isError ? (
                <ErrorNote />
              ) : info ? (
                <>
                  <DataRow label="Images" value={info.library.image_count.toLocaleString()} />
                  <DataRow label="Groups" value={info.library.group_count.toLocaleString()} />
                </>
              ) : null}
            </div>
          </section>

          {/* ── Export ───────────────────────────────────────── */}
          <section className="pt-1">
            <SectionLabel>Export</SectionLabel>
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-zinc-300">Download library</p>
                <p className="text-xs text-zinc-500">Export all images and metadata as a ZIP</p>
              </div>
              <Button
                size="sm"
                variant="outline"
                onClick={handleExportLibrary}
                disabled={exportingLibrary}
                className="gap-1.5 h-8 border-zinc-700 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-300"
              >
                {exportingLibrary ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Download className="h-3.5 w-3.5" />
                )}
                {exportingLibrary ? 'Exporting…' : 'Download'}
              </Button>
            </div>
          </section>

          {/* ── Danger Zone ─────────────────────────────────── */}
          <section className="pt-2 border-t border-red-500/10">
            <SectionLabel>Danger Zone</SectionLabel>
            <div className="space-y-2">
              {/* Delete Library */}
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-zinc-300">Delete library</p>
                  <p className="text-xs text-zinc-500">Remove all images, metadata, and vectors</p>
                </div>
                {purgeJob.isRunning ? (
                  <div className="flex items-center gap-2 text-sm text-zinc-400">
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    <span>
                      {purgeJob.progress ?? 'Deleting…'}
                      {purgeJob.progressPct != null && ` (${purgeJob.progressPct}%)`}
                    </span>
                  </div>
                ) : purgeJob.isComplete ? (
                  <span className="text-sm text-green-400">Done</span>
                ) : purgeJob.isFailed ? (
                  <span className="text-sm text-red-400" title={purgeJob.error ?? undefined}>
                    Failed
                  </span>
                ) : (
                  <Button
                    size="sm"
                    variant="destructive"
                    onClick={() => setConfirmingDelete(true)}
                    className="gap-1.5 h-8"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                    Delete
                  </Button>
                )}
              </div>

              {/* Reset Tags */}
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-zinc-300">Reset tags</p>
                  <p className="text-xs text-zinc-500">
                    Clear all tags and restore default categories
                  </p>
                </div>
                <Button
                  size="sm"
                  variant="destructive"
                  onClick={() => setConfirmingResetTags(true)}
                  disabled={resetTagsMut.isPending}
                  className="gap-1.5 h-8"
                >
                  {resetTagsMut.isPending ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <RotateCcw className="h-3.5 w-3.5" />
                  )}
                  Reset
                </Button>
              </div>
            </div>
          </section>
        </div>

        <ConfirmDialog
          open={confirmingDelete}
          onOpenChange={setConfirmingDelete}
          title="Delete Library"
          description="This will permanently delete all images, thumbnails, metadata, tags, and vector embeddings. This cannot be undone."
          confirmLabel="Delete Everything"
          confirmVariant="destructive"
          loadingLabel="Starting…"
          onConfirm={() => deleteMut.mutate()}
          isLoading={deleteMut.isPending}
        />

        <ConfirmDialog
          open={confirmingResetTags}
          onOpenChange={setConfirmingResetTags}
          title="Reset Tags"
          description="This will delete all tags from every image and reset tag categories to their defaults. This cannot be undone."
          confirmLabel="Reset Tags"
          confirmVariant="destructive"
          loadingLabel="Resetting…"
          onConfirm={() => resetTagsMut.mutate()}
          isLoading={resetTagsMut.isPending}
        />
      </DialogContent>
    </Dialog>
  )
}
