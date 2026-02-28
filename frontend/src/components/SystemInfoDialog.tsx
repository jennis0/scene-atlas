import { useState, useEffect } from 'react'
import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query'
import {
  FolderOpen,
  FolderInput,
  RotateCcw,
  ArrowRight,
  X,
  Trash2,
  Loader2,
  Download,
} from 'lucide-react'
import { Dialog, DialogContent } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { systemApi, getLibraryExportUrl, settingsApi } from '@/lib/api'
import { useJobPolling } from '@/hooks/useJobPolling'
import type { AppSettings } from '@/types'

// ── Types ─────────────────────────────────────────────────────────────────────

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

  return (
    <div className="space-y-2">
      {/* Bar */}
      <div className="flex h-2 rounded-full overflow-hidden bg-secondary gap-px">
        {segments.map(
          (seg) =>
            seg.bytes > 0 && (
              <div
                key={seg.key}
                className={`${seg.color} rounded-full transition-all duration-500`}
                style={{ width: `${Math.max((seg.bytes / total) * 100, 2)}%` }}
              />
            ),
        )}
      </div>
      {/* Legend */}
      <div className="flex flex-wrap gap-x-4 gap-y-1">
        {segments.map(
          (seg) =>
            seg.bytes > 0 && (
              <div key={seg.key} className="flex items-center gap-1.5">
                <div className={`w-2 h-2 rounded-full ${seg.color}`} />
                <span className="text-[11px] text-muted-foreground">
                  {seg.label}{' '}
                  <span className="tabular-nums text-foreground/70">{formatBytes(seg.bytes)}</span>
                </span>
              </div>
            ),
        )}
      </div>
    </div>
  )
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

  const { data: appSettings } = useQuery({
    queryKey: ['app-settings'],
    queryFn: settingsApi.get,
    enabled: open,
  })

  const patchSettingsMut = useMutation({
    mutationFn: (patch: Partial<AppSettings>) => settingsApi.patch(patch),
    onSuccess: (updated) => {
      queryClient.setQueryData(['app-settings'], updated)
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
      <DialogContent className="max-w-[440px] bg-card border-border/50 p-0 overflow-hidden">
        {/* ── Amber stripe ─────────────────────────────────────── */}
        <div className="absolute top-0 inset-x-0 h-0.5 bg-gradient-to-r from-primary/70 via-primary/30 to-transparent pointer-events-none rounded-t-xl" />

        {/* ── Header ─────────────────────────────────────────── */}
        <div
          className="px-4 border-b border-border shrink-0 bg-popover"
          style={{ padding: '10px 12px 10px 16px' }}
        >
          <div className="flex items-center justify-between">
            <div className="flex flex-col">
              <span className="font-display text-[13px] font-medium tracking-[0.06em] text-foreground leading-none">
                System
              </span>
              <div className="mt-[3px] h-px w-7 bg-gradient-to-r from-primary to-transparent" />
            </div>
            <button
              onClick={onClose}
              className="h-7 w-7 rounded flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors"
            >
              <X className="h-3.5 w-3.5" />
              <span className="sr-only">Close</span>
            </button>
          </div>
        </div>

        {/* ── Body ───────────────────────────────────────────── */}
        <div className="px-5 pb-5 pt-4 space-y-5">
          {/* ── Stats row ─────────────────────────────────────── */}
          {isError ? (
            <p className="text-sm text-muted-foreground italic py-2">
              Could not load system information.
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

          {/* ── Storage breakdown ─────────────────────────────── */}
          {!isError && info && <StorageBar storage={info.storage} />}
          {!isError && isLoading && (
            <div className="space-y-2">
              <Shimmer className="h-2 w-full rounded-full" />
              <div className="flex gap-4">
                <Shimmer className="h-3 w-20" />
                <Shimmer className="h-3 w-20" />
                <Shimmer className="h-3 w-20" />
              </div>
            </div>
          )}

          {/* ── Library location (Electron only) ──────────────── */}
          {isElectron && (
            <section>
              <p className="section-label mb-2">Library Location</p>

              {locationPhase === 'restarting' ? (
                <div className="flex items-center gap-2.5 py-2">
                  <RotateCcw className="h-3.5 w-3.5 animate-spin shrink-0 text-primary" />
                  <span className="text-sm text-muted-foreground">Restarting Scene Atlas…</span>
                </div>
              ) : locationPhase === 'confirming' && pendingDir ? (
                <div className="space-y-3">
                  <div className="rounded-md border border-border bg-secondary/40 p-3 space-y-2.5">
                    <div className="space-y-1">
                      <span className="section-label">Current</span>
                      <p className="text-sm text-muted-foreground break-all leading-relaxed">
                        {dataDir ?? '—'}
                      </p>
                    </div>
                    <div className="flex items-center gap-2">
                      <ArrowRight className="h-3 w-3 shrink-0 text-primary/50" />
                      <div className="h-px flex-1 border-t border-dashed border-border" />
                    </div>
                    <div className="space-y-1">
                      <span className="text-[10px] font-semibold text-primary/70 uppercase tracking-[0.1em]">
                        New
                      </span>
                      <p className="text-sm text-primary break-all leading-relaxed">{pendingDir}</p>
                    </div>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    Scene Atlas will restart to apply the new location.
                  </p>
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={handleCancelChange}
                      className="flex-1 h-8"
                    >
                      Cancel
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={handleConfirmChange}
                      className="flex-1 h-8 text-primary border-primary/40 hover:bg-primary/10"
                    >
                      Restart &amp; Apply
                    </Button>
                  </div>
                </div>
              ) : (
                <div className="space-y-2.5">
                  <div className="rounded-md border border-border bg-secondary/40 px-3 py-2.5 min-h-[2.5rem] flex items-center">
                    {dataDir ? (
                      <p className="text-sm text-foreground/80 break-all leading-relaxed">
                        {dataDir}
                      </p>
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
                      className="gap-1.5 h-8"
                    >
                      <FolderOpen className="h-3.5 w-3.5" />
                      Open
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={handleChooseDir}
                      disabled={!dataDir}
                      className="gap-1.5 h-8"
                    >
                      <FolderInput className="h-3.5 w-3.5" />
                      Change Location
                    </Button>
                  </div>
                </div>
              )}
            </section>
          )}

          {/* ── Settings ──────────────────────────────────────── */}
          <section>
            <p className="section-label mb-2.5">Settings</p>
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="text-sm text-foreground/90">Image grid detection</p>
                <p className="text-xs text-muted-foreground leading-relaxed">
                  Analyse battlemap images to detect grid type and cell size
                </p>
              </div>
              <button
                role="switch"
                aria-checked={appSettings?.enable_image_grid_detection ?? false}
                onClick={() =>
                  appSettings &&
                  patchSettingsMut.mutate({
                    enable_image_grid_detection: !appSettings.enable_image_grid_detection,
                  })
                }
                disabled={patchSettingsMut.isPending || !appSettings}
                className={[
                  'shrink-0 relative inline-flex h-5 w-9 cursor-pointer rounded-full border-2 border-transparent',
                  'transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary/40',
                  'disabled:cursor-not-allowed disabled:opacity-50',
                  appSettings?.enable_image_grid_detection ? 'bg-primary' : 'bg-input',
                ].join(' ')}
              >
                <span
                  className={[
                    'pointer-events-none block h-4 w-4 rounded-full bg-background shadow-lg ring-0 transition-transform',
                    appSettings?.enable_image_grid_detection ? 'translate-x-4' : 'translate-x-0',
                  ].join(' ')}
                />
              </button>
            </div>
          </section>

          {/* ── Divider ───────────────────────────────────────── */}
          <div className="border-t border-border/50" />

          {/* ── Actions row ───────────────────────────────────── */}
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant="outline"
              onClick={handleExportLibrary}
              disabled={exportingLibrary}
              className="gap-1.5 h-8"
            >
              {exportingLibrary ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Download className="h-3.5 w-3.5" />
              )}
              {exportingLibrary ? 'Exporting…' : 'Export library'}
            </Button>
          </div>

          {/* ── Danger zone ───────────────────────────────────── */}
          <section className="rounded-md border border-destructive/15 bg-destructive/[0.03] p-3 space-y-2.5">
            <div className="flex items-center justify-between">
              <div className="min-w-0">
                <p className="text-sm text-foreground/90">Delete library</p>
                <p className="text-xs text-muted-foreground">
                  Remove all images, metadata, and vectors
                </p>
              </div>
              {purgeJob.isRunning ? (
                <div className="flex items-center gap-2 text-sm text-muted-foreground shrink-0">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  <span>
                    {purgeJob.progress ?? 'Deleting…'}
                    {purgeJob.progressPct != null && ` (${purgeJob.progressPct}%)`}
                  </span>
                </div>
              ) : purgeJob.isComplete ? (
                <span className="text-sm text-emerald-600 dark:text-emerald-300 shrink-0">
                  Done
                </span>
              ) : purgeJob.isFailed ? (
                <span
                  className="text-sm text-destructive shrink-0"
                  title={purgeJob.error ?? undefined}
                >
                  Failed
                </span>
              ) : (
                <Button
                  size="sm"
                  variant="destructive"
                  onClick={() => setConfirmingDelete(true)}
                  className="gap-1.5 h-7 text-xs shrink-0"
                >
                  <Trash2 className="h-3 w-3" />
                  Delete
                </Button>
              )}
            </div>

            <div className="border-t border-destructive/10" />

            <div className="flex items-center justify-between">
              <div className="min-w-0">
                <p className="text-sm text-foreground/90">Reset tags</p>
                <p className="text-xs text-muted-foreground">
                  Clear all tags and restore default categories
                </p>
              </div>
              <Button
                size="sm"
                variant="destructive"
                onClick={() => setConfirmingResetTags(true)}
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
            </div>
          </section>
        </div>

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
      </DialogContent>
    </Dialog>
  )
}
