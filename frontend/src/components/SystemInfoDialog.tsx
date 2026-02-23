import { useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { FolderOpen, FolderInput, RotateCcw, HardDrive, ArrowRight, X } from 'lucide-react'
import { Dialog, DialogContent } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { systemApi } from '@/lib/api'

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
    <p className="text-xs font-semibold text-zinc-500 tracking-wide uppercase mb-2">
      {children}
    </p>
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
  const [locationPhase, setLocationPhase] = useState<LocationPhase>('idle')
  const [pendingDir, setPendingDir] = useState<string | null>(null)
  const [dataDir, setDataDir] = useState<string | null>(null)

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
          <h2 className="text-xs font-semibold text-zinc-300 tracking-wide uppercase">
            System
          </h2>
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
                    <p className="text-sm text-amber-400 break-all leading-relaxed">{pendingDir}</p>
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
                  <DataRow
                    label="Images"
                    value={info.library.image_count.toLocaleString()}
                  />
                  <DataRow
                    label="Groups"
                    value={info.library.group_count.toLocaleString()}
                  />
                </>
              ) : null}
            </div>
          </section>

        </div>
      </DialogContent>
    </Dialog>
  )
}
