import { useState, useCallback } from 'react'
import { X, Save, RotateCcw, Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { SettingRow } from '@/components/settings/SettingRow'
import { useSettingsDraft } from '@/hooks/useSettingsDraft'
import type { AppSettings } from '@/types'

interface SettingsPanelProps {
  open: boolean
  onClose: () => void
}

export function SettingsPanel({ open, onClose }: SettingsPanelProps) {
  const { settings, draft, setField, isDirty, save, discard, isSaving } = useSettingsDraft()
  const [confirmClose, setConfirmClose] = useState(false)

  // Helper to get current value (draft takes precedence over server settings)
  const val = useCallback(
    (key: keyof AppSettings): string | number | boolean | undefined => {
      return key in draft ? draft[key] : settings?.[key]
    },
    [draft, settings],
  )

  // Unit conversion: bytes to MB and back
  const formatSizeInput = (bytes: number | undefined) => {
    if (bytes === undefined) return ''
    return Math.round(bytes / 1024 / 1024).toString()
  }

  const parseSizeInput = (mb: string) => {
    const num = parseFloat(mb)
    return isNaN(num) ? 0 : Math.round(num * 1024 * 1024)
  }

  const handleClose = () => {
    if (isDirty) {
      setConfirmClose(true)
    } else {
      onClose()
    }
  }

  const handleConfirmClose = () => {
    discard()
    setConfirmClose(false)
    onClose()
  }

  const handleSave = async () => {
    try {
      await save()
      onClose()
    } catch (error) {
      console.error('Failed to save settings:', error)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      handleClose()
    }
  }

  return (
    <>
      {/* Panel backdrop */}
      {open && (
        <div
          className="fixed inset-0 z-40 bg-black/40 transition-opacity duration-300"
          onClick={handleClose}
        />
      )}

      {/* Panel */}
      <div
        role="dialog"
        aria-label="Configuration"
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
            onClick={handleClose}
            className="p-1 hover:bg-secondary rounded transition-colors disabled:opacity-50"
            disabled={!open}
            aria-label="Close settings"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Content */}
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
                onClick={() =>
                  setField('enable_image_grid_detection', !val('enable_image_grid_detection'))
                }
                className={cn(
                  'h-6 w-11 rounded-full transition-colors flex items-center px-1',
                  val('enable_image_grid_detection')
                    ? 'bg-primary'
                    : 'bg-secondary border border-border/50',
                )}
                aria-pressed={val('enable_image_grid_detection')}
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

            <SettingRow label="Max file size" description="Maximum size for individual image files">
              <div className="flex items-center gap-2">
                <input
                  type="number"
                  min="1"
                  max="1000"
                  value={formatSizeInput(val('max_import_file_size'))}
                  onChange={(e) => setField('max_import_file_size', parseSizeInput(e.target.value))}
                  className="w-20 px-2 py-1 rounded bg-secondary border border-border text-sm font-mono text-right"
                  disabled={!open}
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
                  value={formatSizeInput(val('max_video_file_size'))}
                  onChange={(e) => setField('max_video_file_size', parseSizeInput(e.target.value))}
                  className="w-20 px-2 py-1 rounded bg-secondary border border-border text-sm font-mono text-right"
                  disabled={!open}
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
                value={val('max_import_files') ?? ''}
                onChange={(e) => setField('max_import_files', parseInt(e.target.value) || 0)}
                className="w-20 px-2 py-1 rounded bg-secondary border border-border text-sm font-mono text-right"
                disabled={!open}
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
                  value={formatSizeInput(val('max_import_total_size'))}
                  onChange={(e) =>
                    setField('max_import_total_size', parseSizeInput(e.target.value))
                  }
                  className="w-20 px-2 py-1 rounded bg-secondary border border-border text-sm font-mono text-right"
                  disabled={!open}
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
                value={val('max_concurrent_prepare') ?? ''}
                onChange={(e) => setField('max_concurrent_prepare', parseInt(e.target.value) || 1)}
                className="w-16 px-2 py-1 rounded bg-secondary border border-border text-sm font-mono text-right"
                disabled={!open}
              />
            </SettingRow>
          </section>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between gap-2 px-4 py-3 border-t border-border/50 bg-secondary/30">
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              discard()
              setConfirmClose(false)
            }}
            disabled={!isDirty || !open || isSaving}
            className="gap-1.5"
          >
            <RotateCcw className="h-3.5 w-3.5" />
            Discard
          </Button>

          <Button
            variant="default"
            size="sm"
            onClick={handleSave}
            disabled={!isDirty || !open || isSaving}
            className="gap-1.5"
          >
            {isSaving ? (
              <>
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                Saving…
              </>
            ) : (
              <>
                <Save className="h-3.5 w-3.5" />
                Save
              </>
            )}
          </Button>
        </div>
      </div>

      {/* Close confirmation dialog */}
      <ConfirmDialog
        open={confirmClose}
        onOpenChange={setConfirmClose}
        title="Unsaved changes"
        description="You have unsaved changes. Close without saving?"
        confirmLabel="Discard"
        confirmVariant="destructive"
        onConfirm={handleConfirmClose}
      />
    </>
  )
}
