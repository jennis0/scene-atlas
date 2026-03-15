import { useCallback, forwardRef, useImperativeHandle, useState, useEffect } from 'react'
import { AlertCircle, Check } from 'lucide-react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Input } from '@/components/ui/input'
import { SettingRow } from '@/components/settings/SettingRow'
import { useSettingsDraft } from '@/hooks/useSettingsDraft'
import { modelsApi } from '@/lib/api/modelsApi'
import { HARDWARE_BADGE } from '@/lib/modelConstants'
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
    const queryClient = useQueryClient()
    const { settings, draft, setField, save, isDirty, isLoading, isError, error } =
      useSettingsDraft({
        enabled: dialogOpen,
      })

    // Pending model switch (requires confirmation)
    const [pendingModel, setPendingModel] = useState<string | null>(null)

    // Reset pending model when dialog closes to avoid stale confirmation state
    useEffect(() => {
      if (!dialogOpen) setPendingModel(null)
    }, [dialogOpen])

    const { data: modelsData, isLoading: modelsLoading, isError: modelsError } = useQuery({
      queryKey: ['models'],
      queryFn: () => modelsApi.list(),
      enabled: dialogOpen,
    })

    const switchModelMutation = useMutation({
      mutationFn: (modelName: string) => modelsApi.setActiveModel(modelName),
      onSuccess: () => {
        toast.info('Model switch started. This may take a while.')
        queryClient.invalidateQueries({ queryKey: ['models'] })
        queryClient.invalidateQueries({ queryKey: ['appSettings'] })
        setPendingModel(null)
      },
      onError: () => {
        toast.error('Failed to switch model.')
      },
    })

    const deleteEmbeddingsMutation = useMutation({
      mutationFn: (modelName: string) => modelsApi.deleteEmbeddings(modelName),
      onSuccess: () => {
        toast.success('Embeddings deleted.')
        queryClient.invalidateQueries({ queryKey: ['models'] })
      },
      onError: () => {
        toast.error('Failed to delete embeddings.')
      },
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
            {/* ── AI Model ────────────────────────────────────────────────────── */}
            <section className="space-y-3">
              <p className="section-label mb-3">AI Model</p>

              {/* Active model display */}
              <p className="text-xs text-muted-foreground">
                Active model:{' '}
                <span className="font-medium text-foreground">
                  {settings?.active_model || '(auto-detecting)'}
                </span>
              </p>

              {/* Model cards */}
              {modelsLoading && (
                <p className="text-xs text-muted-foreground">Loading models…</p>
              )}
              {modelsError && (
                <p className="text-xs text-destructive">Could not load model list</p>
              )}
              {modelsData && modelsData.models.length > 0 && (
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 mt-2">
                  {modelsData.models.map((model) => {
                    const isActive = model.active
                    const isPending = pendingModel === model.name
                    const hwBadge = HARDWARE_BADGE[model.recommended_hardware] ?? HARDWARE_BADGE['any']

                    return (
                      <button
                        key={model.name}
                        type="button"
                        onClick={() => {
                          if (isActive) return
                          if (isPending) {
                            switchModelMutation.mutate(model.name)
                          } else {
                            setPendingModel(model.name)
                          }
                        }}
                        className={`relative text-left rounded-lg border p-3 space-y-1.5 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 ${
                          isActive
                            ? 'border-primary bg-primary/5 cursor-default'
                            : isPending
                              ? 'border-amber-400 bg-amber-50 dark:bg-amber-900/20 hover:bg-amber-50/80'
                              : 'border-border bg-card hover:border-border/80 hover:bg-accent/30'
                        }`}
                      >
                        {/* Active checkmark */}
                        {isActive && (
                          <span className="absolute top-2 right-2 text-primary">
                            <Check className="h-3.5 w-3.5" />
                          </span>
                        )}

                        {/* Label + hardware badge */}
                        <div className="flex items-center gap-1.5 flex-wrap">
                          <span className="font-medium text-xs">{model.label}</span>
                          <span
                            className={`text-[10px] font-medium px-1 py-0.5 rounded ${hwBadge.className}`}
                          >
                            {hwBadge.label}
                          </span>
                          {!model.downloaded && (
                            <span className="text-[10px] font-medium px-1 py-0.5 rounded bg-muted text-muted-foreground">
                              Not downloaded
                            </span>
                          )}
                        </div>

                        {/* Description */}
                        <p className="text-[11px] text-muted-foreground leading-relaxed">
                          {model.description}
                        </p>

                        {/* Size */}
                        <p className="text-[10px] text-muted-foreground">
                          ~{model.approx_size_mb} MB
                        </p>
                      </button>
                    )
                  })}
                </div>
              )}

              {/* Pending switch confirmation banner */}
              {pendingModel && (
                <div className="rounded-md border border-amber-300 bg-amber-50 dark:bg-amber-900/20 dark:border-amber-700 p-3 text-xs space-y-2">
                  <p className="text-amber-800 dark:text-amber-200">
                    Switching models will re-process all images. This can take a while.
                  </p>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={() => switchModelMutation.mutate(pendingModel)}
                      disabled={switchModelMutation.isPending}
                      className="px-3 py-1 rounded bg-primary text-primary-foreground text-xs font-medium hover:bg-primary/90 disabled:opacity-50 transition-colors"
                    >
                      {switchModelMutation.isPending ? 'Switching…' : 'Confirm switch'}
                    </button>
                    <button
                      type="button"
                      onClick={() => setPendingModel(null)}
                      className="px-3 py-1 rounded border border-border text-xs hover:bg-accent transition-colors"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              )}

              {/* Stale embeddings section */}
              {modelsData &&
                modelsData.models.some((m) => !m.active && m.downloaded) && (
                  <div className="space-y-2 pt-1">
                    <p className="text-xs font-medium">Stale Embeddings</p>
                    <p className="text-xs text-muted-foreground">
                      You can free up storage by deleting embeddings for models you no longer use.
                    </p>
                    <div className="space-y-1">
                      {modelsData.models
                        .filter((m) => !m.active && m.downloaded)
                        .map((model) => (
                          <div key={model.name} className="flex items-center justify-between gap-2">
                            <span className="text-xs text-muted-foreground">{model.label}</span>
                            <button
                              type="button"
                              onClick={() => deleteEmbeddingsMutation.mutate(model.name)}
                              disabled={deleteEmbeddingsMutation.isPending && deleteEmbeddingsMutation.variables === model.name}
                              className="text-xs text-destructive hover:underline disabled:opacity-50"
                            >
                              Delete embeddings
                            </button>
                          </div>
                        ))}
                    </div>
                  </div>
                )}

              <div className="border-t border-border/30" />
            </section>

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
