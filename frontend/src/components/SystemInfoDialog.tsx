import { useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { FolderOpen, FolderInput, RotateCcw, HardDrive, ArrowRight } from 'lucide-react'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
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
  return <div className={`rounded animate-pulse bg-muted/25 ${className}`} />
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-2.5 mb-3">
      <div
        className="h-3.5 w-0.5 rounded-full shrink-0"
        style={{ background: 'hsl(38 60% 58% / 0.7)' }}
      />
      <span className="font-mono text-[9px] tracking-[0.18em] uppercase text-muted-foreground/60">
        {children}
      </span>
    </div>
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
    <div className="flex items-baseline justify-between py-0.5">
      <span
        className={`font-mono text-[11px] ${
          highlight ? 'text-foreground/80' : 'text-muted-foreground/60'
        }`}
      >
        {label}
      </span>
      <span
        className={`font-mono text-[11px] tabular-nums ${highlight ? 'font-medium' : ''}`}
        style={{ color: highlight ? 'hsl(38 60% 58%)' : 'hsl(38 60% 58% / 0.75)' }}
      >
        {value}
      </span>
    </div>
  )
}

function DataRowSkeleton({ wide = false }: { wide?: boolean }) {
  return (
    <div className="flex items-baseline justify-between py-0.5">
      <Shimmer className={`h-2.5 ${wide ? 'w-24' : 'w-16'}`} />
      <Shimmer className="h-2.5 w-14" />
    </div>
  )
}

function ErrorNote() {
  return (
    <p className="font-mono text-[10px] text-muted-foreground/40 italic py-1">
      Could not load system information.
    </p>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export function SystemInfoDialog({ open, onClose }: SystemInfoDialogProps) {
  const [locationPhase, setLocationPhase] = useState<LocationPhase>('idle')
  const [pendingDir, setPendingDir] = useState<string | null>(null)
  const [dataDir, setDataDir] = useState<string | null>(null)

  // Load current data dir when dialog opens
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
      // Reset after close animation completes
      setTimeout(() => {
        setLocationPhase('idle')
        setPendingDir(null)
      }, 200)
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent
        className="max-w-[440px] bg-background border-border/50 p-0 overflow-hidden"
        style={{
          boxShadow:
            '0 24px 64px -12px hsl(38 60% 58% / 0.08), 0 8px 32px rgba(0,0,0,0.7)',
        }}
      >
        {/* Header */}
        <div
          className="px-6 py-5 border-b border-border/40"
          style={{
            background:
              'linear-gradient(180deg, hsl(38 60% 58% / 0.06) 0%, transparent 100%)',
          }}
        >
          <DialogHeader>
            <DialogTitle className="flex items-center gap-3">
              <div className="flex h-8 w-8 items-center justify-center rounded border border-border/40 bg-muted/20 shrink-0">
                <HardDrive
                  className="h-4 w-4"
                  style={{ color: 'hsl(38 60% 58%)' }}
                />
              </div>
              <div>
                <div className="font-display text-base font-medium tracking-wide text-foreground leading-none">
                  System
                </div>
                <div className="font-mono text-[9px] tracking-[0.18em] text-muted-foreground/50 uppercase mt-1">
                  Storage &amp; Library
                </div>
              </div>
            </DialogTitle>
          </DialogHeader>
        </div>

        {/* Body */}
        <div className="px-6 py-5 space-y-6">

          {/* ── Library Location ──────────────────────────────── */}
          <section>
            <SectionLabel>Library Location</SectionLabel>

            {locationPhase === 'restarting' ? (
              <div className="flex items-center gap-3 py-3">
                <RotateCcw
                  className="h-3.5 w-3.5 animate-spin shrink-0"
                  style={{ color: 'hsl(38 60% 58%)' }}
                />
                <span className="font-mono text-xs text-muted-foreground/70">
                  Restarting Scene Atlas…
                </span>
              </div>
            ) : locationPhase === 'confirming' && pendingDir ? (
              <div className="space-y-3">
                {/* Before / after panel */}
                <div className="rounded border border-border/40 bg-muted/10 p-3 space-y-2.5">
                  <div className="space-y-1">
                    <span className="font-mono text-[9px] tracking-widest uppercase text-muted-foreground/40">
                      Current
                    </span>
                    <p className="font-mono text-[11px] text-muted-foreground/60 break-all leading-relaxed">
                      {dataDir ?? '—'}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <ArrowRight
                      className="h-3 w-3 shrink-0"
                      style={{ color: 'hsl(38 60% 58% / 0.5)' }}
                    />
                    <div className="h-px flex-1 border-t border-dashed border-border/30" />
                  </div>
                  <div className="space-y-1">
                    <span
                      className="font-mono text-[9px] tracking-widest uppercase"
                      style={{ color: 'hsl(38 60% 58% / 0.7)' }}
                    >
                      New
                    </span>
                    <p
                      className="font-mono text-[11px] break-all leading-relaxed"
                      style={{ color: 'hsl(38 60% 58%)' }}
                    >
                      {pendingDir}
                    </p>
                  </div>
                </div>
                <p className="font-mono text-[10px] text-muted-foreground/40">
                  Scene Atlas will restart to apply the new location.
                </p>
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={handleCancelChange}
                    className="flex-1 h-8 font-mono text-xs"
                  >
                    Cancel
                  </Button>
                  <Button
                    size="sm"
                    onClick={handleConfirmChange}
                    className="flex-1 h-8 font-mono text-xs border"
                    style={{
                      background: 'hsl(38 60% 58% / 0.12)',
                      borderColor: 'hsl(38 60% 58% / 0.35)',
                      color: 'hsl(38 60% 65%)',
                    }}
                  >
                    Restart &amp; Apply
                  </Button>
                </div>
              </div>
            ) : (
              <div className="space-y-3">
                {/* Path display */}
                <div className="rounded border border-border/40 bg-muted/10 px-3 py-2.5 min-h-[2.5rem] flex items-center">
                  {dataDir ? (
                    <p className="font-mono text-[11px] text-muted-foreground/75 break-all leading-relaxed">
                      {dataDir}
                    </p>
                  ) : (
                    <Shimmer className="h-2.5 w-3/4" />
                  )}
                </div>
                {/* Actions */}
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={handleOpenInExplorer}
                    disabled={!dataDir}
                    className="gap-1.5 h-8 font-mono text-xs"
                  >
                    <FolderOpen className="h-3.5 w-3.5" />
                    Open
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={handleChooseDir}
                    disabled={!dataDir}
                    className="gap-1.5 h-8 font-mono text-xs"
                  >
                    <FolderInput className="h-3.5 w-3.5" />
                    Change Location
                  </Button>
                </div>
              </div>
            )}
          </section>

          {/* ── Storage ───────────────────────────────────────── */}
          <section>
            <SectionLabel>Storage</SectionLabel>
            <div className="space-y-1">
              {isLoading ? (
                <>
                  <DataRowSkeleton />
                  <DataRowSkeleton />
                  <DataRowSkeleton />
                  <div className="mt-1.5 pt-2 border-t border-border/30">
                    <DataRowSkeleton wide />
                  </div>
                </>
              ) : isError ? (
                <ErrorNote />
              ) : info ? (
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
                  <div className="mt-1.5 pt-2 border-t border-border/30">
                    <DataRow
                      label="Total"
                      value={formatBytes(info.storage.total_bytes)}
                      highlight
                    />
                  </div>
                </>
              ) : null}
            </div>
          </section>

          {/* ── Collection ────────────────────────────────────── */}
          <section className="pb-1">
            <SectionLabel>Collection</SectionLabel>
            <div className="space-y-1">
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
