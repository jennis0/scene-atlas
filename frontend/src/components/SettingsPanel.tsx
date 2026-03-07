import { useCallback, useEffect, useRef } from 'react'
import { toast } from 'sonner'
import { X, AlertCircle } from 'lucide-react'
import { cn } from '@/lib/utils'
import { SettingRow } from '@/components/settings/SettingRow'
import { useSettingsDraft } from '@/hooks/useSettingsDraft'
import type { AppSettings } from '@/types'

interface SettingsPanelProps {
  open: boolean
  onClose: () => void
}

export function SettingsPanel({ open, onClose }: SettingsPanelProps) {
  const { settings, draft, setField, save, isLoading, isError, error, isSaving } = useSettingsDraft(
    {
      enabled: open, // Only fetch settings when panel is actually open
    },
  )
  const panelRef = useRef<HTMLDivElement>(null)

  // Auto-save on blur
  const handleBlur = useCallback(
    async (e: React.FocusEvent<HTMLInputElement | HTMLButtonElement>) => {
      // Don't save if user is moving focus within the panel
      if (panelRef.current && panelRef.current.contains(e.relatedTarget as Node)) {
        return
      }
      // Save any pending changes
      try {
        await save()
        toast.success('Settings saved', { duration: 2000 })
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Failed to save settings'
        toast.error(message)
        console.error('Auto-save failed:', err)
      }
    },
    [save],
  )

  // Move focus to panel on open
  useEffect(() => {
    if (open && panelRef.current) {
      // Focus the close button so user can Escape to close
      const closeBtn = panelRef.current.querySelector(
        'button[aria-label="Close settings"]',
      ) as HTMLButtonElement
      if (closeBtn) {
        closeBtn.focus()
      }
    }
  }, [open])

  // Helper to get current value (draft takes precedence over server settings)
  const val = useCallback(
    <K extends keyof AppSettings>(key: K): AppSettings[K] | undefined => {
      return (key in draft ? draft[key] : settings?.[key]) as AppSettings[K] | undefined
    },
    [draft, settings],
  )

  // Unit conversion: bytes to MB and back (with validation)
  const formatSizeInput = (bytes: number | undefined) => {
    if (bytes === undefined || bytes === 0) return ''
    return Math.round(bytes / 1024 / 1024).toString()
  }

  const parseSizeInput = (mb: string): number => {
    if (!mb || mb.trim() === '') return 0
    const num = parseFloat(mb)
    if (isNaN(num) || num <= 0) return 0
    return Math.round(num * 1024 * 1024)
  }

  const parseIntInput = (str: string): number => {
    if (!str || str.trim() === '') return 0
    const num = parseInt(str, 10)
    if (isNaN(num) || num <= 0) return 0
    return num
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      onClose()
    }
  }

  return (
    <>
      {/* Panel backdrop */}
      {open && (
        <div
          className="fixed inset-0 z-40 bg-black/40 transition-opacity duration-300"
          onClick={onClose}
        />
      )}

      {/* Panel */}
      <div
        ref={panelRef}
        role="dialog"
        aria-label="Configuration"
        aria-modal="true"
        className={cn(
          'fixed right-0 inset-y-4 z-50 flex flex-col',
          'w-[560px] rounded-l-xl',
          'bg-card border-l border-y border-border shadow-2xl',
          'transition-transform duration-300 ease-in-out',
          open ? 'translate-x-0' : 'translate-x-full',
        )}
        {...(!open && { inert: true })}
        tabIndex={open ? 0 : -1}
        onKeyDown={handleKeyDown}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-border/50">
          <h2 className="text-base font-semibold">Settings</h2>
          <button
            onClick={onClose}
            className="p-1 hover:bg-secondary rounded transition-colors disabled:opacity-50"
            disabled={!open}
            aria-label="Close settings"
            onBlur={handleBlur}
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Error state */}
        {isError && error && (
          <div className="mx-4 mt-3 p-3 rounded bg-destructive/10 border border-destructive/30 flex items-start gap-2">
            <AlertCircle className="h-4 w-4 text-destructive mt-0.5 flex-shrink-0" />
            <div className="text-sm text-destructive">
              <p className="font-semibold">Failed to load settings</p>
              <p className="text-xs">{error.message || 'Please try again'}</p>
            </div>
          </div>
        )}

        {/* Loading skeleton */}
        {isLoading && (
          <div className="flex-1 px-4 py-4 space-y-4">
            {[...Array(6)].map((_, i) => (
              <div key={i} className="space-y-2">
                <div className="h-4 bg-muted rounded w-32 animate-pulse" />
                <div className="h-3 bg-muted rounded w-48 animate-pulse" />
                <div className="h-8 bg-muted rounded w-20 animate-pulse mt-2" />
              </div>
            ))}
          </div>
        )}

        {/* Content (hidden during load/error) */}
        {!isLoading && !isError && (
          <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
            {/* ── General ─────────────────────────────────────────────────────── */}
            <section className="space-y-3">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                General
              </h3>

              <SettingRow
                label="Grid detection"
                description="Automatically detect grids on imported battlemaps"
              >
                <button
                  type="button"
                  onClick={() => {
                    const current = val('enable_image_grid_detection')
                    setField('enable_image_grid_detection', !current)
                  }}
                  aria-label="Toggle grid detection"
                  aria-pressed={val('enable_image_grid_detection') as boolean}
                  onBlur={handleBlur}
                  className={cn(
                    'h-6 w-11 rounded-full transition-colors flex items-center px-1',
                    'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40',
                    val('enable_image_grid_detection')
                      ? 'bg-primary'
                      : 'bg-secondary border border-border/50',
                  )}
                  disabled={!open}
                >
                  <div
                    className={cn(
                      'h-4 w-4 rounded-full bg-white shadow-sm transition-transform',
                      val('enable_image_grid_detection') ? 'translate-x-5' : 'translate-x-0',
                    )}
                  />
                </button>
              </SettingRow>

              <div className="border-t border-border/50" />
            </section>

            {/* ── Import Limits ───────────────────────────────────────────────── */}
            <section className="space-y-3">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Import Limits
              </h3>

              <SettingRow
                label="Max file size"
                description="Maximum size for individual image files"
              >
                <div className="flex items-center gap-2">
                  <input
                    type="number"
                    min="1"
                    max="1000"
                    inputMode="decimal"
                    value={formatSizeInput(val('max_import_file_size'))}
                    onChange={(e) =>
                      setField('max_import_file_size', parseSizeInput(e.target.value))
                    }
                    onBlur={handleBlur}
                    className="w-20 px-2 py-1 rounded bg-secondary border border-border text-sm font-mono text-right focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
                    disabled={!open}
                    aria-label="Max file size in MB"
                  />
                  <span className="text-xs text-muted-foreground">MB</span>
                </div>
              </SettingRow>

              <SettingRow label="Max video size" description="Maximum size for video files">
                <div className="flex items-center gap-2">
                  <input
                    type="number"
                    min="1"
                    max="5000"
                    inputMode="decimal"
                    value={formatSizeInput(val('max_video_file_size'))}
                    onChange={(e) =>
                      setField('max_video_file_size', parseSizeInput(e.target.value))
                    }
                    onBlur={handleBlur}
                    className="w-20 px-2 py-1 rounded bg-secondary border border-border text-sm font-mono text-right focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
                    disabled={!open}
                    aria-label="Max video size in MB"
                  />
                  <span className="text-xs text-muted-foreground">MB</span>
                </div>
              </SettingRow>

              <SettingRow
                label="Max files per import"
                description="Maximum number of files in a single import"
              >
                <input
                  type="number"
                  min="1"
                  max="10000"
                  inputMode="numeric"
                  value={(val('max_import_files') as number) ?? ''}
                  onChange={(e) => setField('max_import_files', parseIntInput(e.target.value))}
                  onBlur={handleBlur}
                  className="w-20 px-2 py-1 rounded bg-secondary border border-border text-sm font-mono text-right focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
                  disabled={!open}
                  aria-label="Max files per import"
                />
              </SettingRow>

              <SettingRow
                label="Max total upload size"
                description="Maximum total size for all files in one import"
              >
                <div className="flex items-center gap-2">
                  <input
                    type="number"
                    min="1"
                    max="50000"
                    inputMode="decimal"
                    value={formatSizeInput(val('max_import_total_size'))}
                    onChange={(e) =>
                      setField('max_import_total_size', parseSizeInput(e.target.value))
                    }
                    onBlur={handleBlur}
                    className="w-20 px-2 py-1 rounded bg-secondary border border-border text-sm font-mono text-right focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
                    disabled={!open}
                    aria-label="Max total upload size in MB"
                  />
                  <span className="text-xs text-muted-foreground">MB</span>
                </div>
              </SettingRow>

              <div className="border-t border-border/50" />
            </section>

            {/* ── Performance ─────────────────────────────────────────────────── */}
            <section className="space-y-3">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Performance
              </h3>

              <SettingRow
                label="Concurrent imports"
                description="Number of simultaneous import jobs (1-16)"
                requiresRestart={true}
              >
                <input
                  type="number"
                  min="1"
                  max="16"
                  inputMode="numeric"
                  value={(val('max_concurrent_prepare') as number) ?? ''}
                  onChange={(e) =>
                    setField('max_concurrent_prepare', parseIntInput(e.target.value))
                  }
                  onBlur={handleBlur}
                  className="w-16 px-2 py-1 rounded bg-secondary border border-border text-sm font-mono text-right focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
                  disabled={!open}
                  aria-label="Concurrent imports (1-16)"
                />
              </SettingRow>
            </section>
          </div>
        )}

        {/* Footer status */}
        {isSaving && (
          <div className="px-4 py-2 text-xs text-muted-foreground text-center">Saving…</div>
        )}
      </div>
    </>
  )
}
