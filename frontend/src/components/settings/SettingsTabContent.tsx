import { useCallback, forwardRef, useImperativeHandle } from 'react'
import { AlertCircle } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { SettingRow } from '@/components/settings/SettingRow'
import { useSettingsDraft } from '@/hooks/useSettingsDraft'
import type { AppSettings } from '@/types'

export interface SettingsTabContentRef {
  save: () => Promise<void>
  isDirty: boolean
}

interface SettingsTabContentProps {
  dialogOpen: boolean
}

export const SettingsTabContent = forwardRef<SettingsTabContentRef, SettingsTabContentProps>(
  ({ dialogOpen }, ref) => {
    const { settings, draft, setField, save, isDirty, isLoading, isError, error } =
      useSettingsDraft({
        enabled: dialogOpen,
      })

    useImperativeHandle(
      ref,
      () => ({
        save: async () => {
          await save()
        },
        isDirty,
      }),
      [save, isDirty],
    )

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

    return (
      <div className="min-h-[220px]">
        {/* Error state */}
        {isError && error && (
          <div className="mb-4 p-3 rounded bg-destructive/10 border border-destructive/30 flex items-start gap-2">
            <AlertCircle className="h-4 w-4 text-destructive mt-0.5 flex-shrink-0" />
            <div className="text-sm text-destructive">
              <p className="font-semibold">Failed to load settings</p>
              <p className="text-xs">{error.message || 'Please try again'}</p>
            </div>
          </div>
        )}

        {/* Loading skeleton */}
        {isLoading && (
          <div className="space-y-4">
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
          <div className="space-y-4">
            {/* ── General ─────────────────────────────────────────────────────── */}
            <section className="space-y-3">
              <p className="section-label mb-3">General</p>

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
                  className={`h-6 w-11 rounded-full transition-colors flex items-center px-1 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary/40 ${
                    val('enable_image_grid_detection')
                      ? 'bg-primary'
                      : 'bg-secondary border border-border/50'
                  }`}
                >
                  <div
                    className={`h-4 w-4 rounded-full bg-white shadow-sm transition-transform ${
                      val('enable_image_grid_detection') ? 'translate-x-5' : 'translate-x-0'
                    }`}
                  />
                </button>
              </SettingRow>

              <div className="border-t border-border/30" />
            </section>

            {/* ── Import Limits ───────────────────────────────────────────────── */}
            <section className="space-y-3">
              <p className="section-label mb-3">Import Limits</p>

              <SettingRow
                label="Max file size"
                description="Maximum size for individual image files"
              >
                <div className="flex items-center gap-2">
                  <Input
                    type="number"
                    inputSize="compact"
                    min="1"
                    max="1000"
                    inputMode="decimal"
                    value={formatSizeInput(val('max_import_file_size'))}
                    onChange={(e) =>
                      setField('max_import_file_size', parseSizeInput(e.target.value))
                    }
                    className="w-20 text-right font-mono [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
                    aria-label="Max file size in MB"
                  />
                  <span className="w-8 shrink-0 text-xs text-muted-foreground">MB</span>
                </div>
              </SettingRow>

              <SettingRow label="Max video size" description="Maximum size for video files">
                <div className="flex items-center gap-2">
                  <Input
                    type="number"
                    inputSize="compact"
                    min="1"
                    max="5000"
                    inputMode="decimal"
                    value={formatSizeInput(val('max_video_file_size'))}
                    onChange={(e) =>
                      setField('max_video_file_size', parseSizeInput(e.target.value))
                    }
                    className="w-20 text-right font-mono [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
                    aria-label="Max video size in MB"
                  />
                  <span className="w-8 shrink-0 text-xs text-muted-foreground">MB</span>
                </div>
              </SettingRow>

              <SettingRow
                label="Max files per import"
                description="Maximum number of files in a single import"
              >
                <div className="flex items-center gap-2">
                  <Input
                    type="number"
                    inputSize="compact"
                    min="1"
                    max="10000"
                    inputMode="numeric"
                    value={(val('max_import_files') as number) ?? ''}
                    onChange={(e) => setField('max_import_files', parseIntInput(e.target.value))}
                    className="w-20 text-right font-mono [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
                    aria-label="Max files per import"
                  />
                  <span className="w-8 shrink-0" />
                </div>
              </SettingRow>

              <SettingRow
                label="Max total upload size"
                description="Maximum total size for all files in one import"
              >
                <div className="flex items-center gap-2">
                  <Input
                    type="number"
                    inputSize="compact"
                    min="1"
                    max="50000"
                    inputMode="decimal"
                    value={formatSizeInput(val('max_import_total_size'))}
                    onChange={(e) =>
                      setField('max_import_total_size', parseSizeInput(e.target.value))
                    }
                    className="w-20 text-right font-mono [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
                    aria-label="Max total upload size in MB"
                  />
                  <span className="w-8 shrink-0 text-xs text-muted-foreground">MB</span>
                </div>
              </SettingRow>

              <div className="border-t border-border/30" />
            </section>

            {/* ── Performance ─────────────────────────────────────────────────── */}
            <section className="space-y-3">
              <p className="section-label mb-3">Performance</p>

              <SettingRow
                label="Concurrent imports"
                description="Number of simultaneous import jobs (1-16)"
                requiresRestart={true}
              >
                <div className="flex items-center gap-2">
                  <Input
                    type="number"
                    inputSize="compact"
                    min="1"
                    max="16"
                    inputMode="numeric"
                    value={(val('max_concurrent_prepare') as number) ?? ''}
                    onChange={(e) =>
                      setField('max_concurrent_prepare', parseIntInput(e.target.value))
                    }
                    className="w-16 text-right font-mono [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
                    aria-label="Concurrent imports (1-16)"
                  />
                  <span className="w-8 shrink-0" />
                </div>
              </SettingRow>
            </section>
          </div>
        )}
      </div>
    )
  },
)

SettingsTabContent.displayName = 'SettingsTabContent'
