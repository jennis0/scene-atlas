import { useCallback, forwardRef, useImperativeHandle, useState, useEffect } from 'react'
import { AlertCircle, Check } from 'lucide-react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { SettingRow } from '@/components/settings/SettingRow'
import { SettingsSection } from '@/components/settings/SettingsSection'
import { ToggleSwitch } from '@/components/settings/ToggleSwitch'
import { NumberSetting } from '@/components/settings/NumberSetting'
import { SegmentedControl } from '@/components/settings/SegmentedControl'
import { useSettingsDraft } from '@/hooks/useSettingsDraft'
import { useStorageDirs } from '@/hooks/useStorageDirs'
import { getApiErrorMessage } from '@/lib/getErrorMessage'
import { QUERY_KEYS, invalidateTagQueries } from '@/lib/queryKeys'
import { modelsApi } from '@/lib/api/modelsApi'
import { useImportManagerSnapshot } from '@/lib/import/useImports'
import { isFinished } from '@/components/imports/format'
import { HARDWARE_BADGE } from '@/lib/modelConstants'
import { useHueColor } from '@/contexts/TagColorContext'
import { tagApi } from '@/lib/api/tagApi'
import { TagPackCard } from '@/components/setup/TagPackCard'
import type { AppSettings } from '@/types'

/** Longest side analysed for grids (0 = full resolution). Lower is faster, but in
 * evaluation 4096 px missed most thin-line 200 dpi maps (design/grid-detection-v3.md). */
const GRID_RESOLUTION_OPTIONS = [
  { value: 0, label: 'Full', title: 'Analyse every map at full resolution (recommended)' },
  { value: 8192, label: '8K', title: 'Reduce maps larger than 8192 px' },
  { value: 4096, label: '4K', title: 'Reduce maps larger than 4096 px; misses thin grid lines' },
] as const

const STORED_FORMAT_OPTIONS = [
  { value: 'original', label: 'Original', title: 'Keep each file exactly as uploaded' },
  { value: 'webp', label: 'WebP', title: 'Smallest files; lossless for PNGs' },
  { value: 'jpeg', label: 'JPEG', title: 'Small files; images with transparency stay as uploaded' },
  { value: 'png', label: 'PNG', title: 'Lossless, but usually larger than the original' },
] as const

interface StoragePathRowProps {
  label: string
  description: string
  current: string | null
  pending: string | null
  onBrowse: () => void
  requiresRestart?: boolean
}

function StoragePathRow({
  label,
  description,
  current,
  pending,
  onBrowse,
  requiresRestart,
}: StoragePathRowProps) {
  const display = pending ?? current ?? '—'
  const changed = pending != null
  return (
    <SettingRow label={label} description={description} requiresRestart={requiresRestart}>
      <div className="flex items-center gap-2">
        <span
          className={`max-w-[10.59rem] truncate text-xs font-mono ${changed ? 'text-primary' : 'text-muted-foreground'}`}
          title={display}
        >
          {display}
        </span>
        <button
          type="button"
          onClick={onBrowse}
          className="shrink-0 rounded border border-border/50 px-2 py-1 text-xs text-muted-foreground hover:text-foreground"
        >
          Browse
        </button>
      </div>
    </SettingRow>
  )
}

function TagPacksSection({ dialogOpen }: { dialogOpen: boolean }) {
  const queryClient = useQueryClient()

  const { data: packs, isLoading } = useQuery({
    queryKey: QUERY_KEYS.tagPacks,
    queryFn: tagApi.getTagPacks,
    enabled: dialogOpen,
  })

  const importMutation = useMutation({
    mutationFn: (packName: string) => tagApi.importTagPack(packName),
    onSuccess: (result, packName) => {
      const pack = packs?.find((p) => p.name === packName)
      const label = pack?.label ?? packName
      if (result.tags_added > 0) {
        toast.success(`Imported ${result.tags_added} new tags from ${label}`)
      } else {
        toast.info(`${label} — all tags already present`)
      }
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.tagPacks })
      invalidateTagQueries(queryClient)
    },
    onError: (_err, packName) => {
      toast.error(`Failed to import ${packName}`)
    },
  })

  return (
    <SettingsSection
      title="Tag Packs"
      description="Import genre-specific tag vocabularies for auto-detection and filtering."
    >
      {isLoading && (
        <div className="grid grid-cols-2 gap-2">
          {[...Array(6)].map((_, i) => (
            <div key={i} className="h-16 bg-muted/40 rounded animate-pulse" />
          ))}
        </div>
      )}

      {packs && (
        <div className="grid grid-cols-2 gap-2">
          {packs.map((pack) => (
            <TagPackCard
              key={pack.name}
              pack={pack}
              onImport={() => importMutation.mutate(pack.name)}
              isImporting={importMutation.isPending && importMutation.variables === pack.name}
            />
          ))}
        </div>
      )}
    </SettingsSection>
  )
}

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
    const hueColor = useHueColor()
    const { settings, draft, setField, save, isDirty, isLoading, isError, error } =
      useSettingsDraft({
        enabled: dialogOpen,
      })

    const [pendingModel, setPendingModel] = useState<string | null>(null)
    // Imports keep going across a model switch: the server pauses them while
    // the model changes, then they carry on. Just say so.
    const activeImportCount = useImportManagerSnapshot().jobs.filter((j) => !isFinished(j)).length

    // Reset pending model when dialog closes to avoid stale confirmation state
    useEffect(() => {
      if (!dialogOpen) {
        setPendingModel(null)
      }
    }, [dialogOpen])

    const handleModelSelect = useCallback((modelName: string) => {
      setPendingModel(modelName)
    }, [])

    const {
      data: modelsData,
      isLoading: modelsLoading,
      isError: modelsError,
    } = useQuery({
      queryKey: QUERY_KEYS.models,
      queryFn: () => modelsApi.list(),
      enabled: dialogOpen,
    })

    const switchModelMutation = useMutation({
      mutationFn: (modelName: string) => modelsApi.setActiveModel(modelName),
      onSuccess: () => {
        toast.info('Model switch started. This may take a while.')
        queryClient.invalidateQueries({ queryKey: QUERY_KEYS.models })
        queryClient.invalidateQueries({ queryKey: QUERY_KEYS.appSettings })
        setPendingModel(null)
      },
      onError: (err) => {
        toast.error(getApiErrorMessage(err, 'Failed to switch model.'))
      },
    })

    const deleteEmbeddingsMutation = useMutation({
      mutationFn: (modelName: string) => modelsApi.deleteEmbeddings(modelName),
      onSuccess: () => {
        toast.success('Embeddings deleted.')
        queryClient.invalidateQueries({ queryKey: QUERY_KEYS.models })
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

    const isElectron = typeof window !== 'undefined' && !!window.electronAPI
    const { appDataDir, imageLibraryDir } = useStorageDirs(dialogOpen)
    const [pendingAppDataDir, setPendingAppDataDir] = useState<string | null>(null)
    const [pendingImageLibraryDir, setPendingImageLibraryDir] = useState<string | null>(null)

    const handleChooseAppDataDir = async () => {
      const chosen = await window.electronAPI?.chooseAppDataDir()
      if (chosen && chosen !== appDataDir) setPendingAppDataDir(chosen)
    }

    const handleChooseImageLibraryDir = async () => {
      const chosen = await window.electronAPI?.chooseImageLibraryDir()
      if (chosen && chosen !== imageLibraryDir) setPendingImageLibraryDir(chosen)
    }

    const handleApplyStorageChange = async () => {
      if (!appDataDir || !imageLibraryDir) return // IPC hasn't loaded yet; wait
      // On success the app relaunches and this never resolves.
      const result = await window.electronAPI?.changeStorageDirs(
        pendingAppDataDir ?? appDataDir,
        pendingImageLibraryDir ?? imageLibraryDir,
      )
      if (result?.error) toast.error(result.error)
    }

    // Draft takes precedence over server settings
    const val = useCallback(
      <K extends keyof AppSettings>(key: K): AppSettings[K] | undefined => {
        return (key in draft ? draft[key] : settings?.[key]) as AppSettings[K] | undefined
      },
      [draft, settings],
    )

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
      <div className="min-h-[12.94rem]">
        {isError && error && (
          <div className="mb-4 p-3 rounded bg-destructive/10 border border-destructive/30 flex items-start gap-2">
            <AlertCircle className="h-4 w-4 text-destructive mt-0.5 flex-shrink-0" />
            <div className="text-sm text-destructive">
              <p className="font-semibold">Failed to load settings</p>
              <p className="text-xs">{error.message || 'Please try again'}</p>
            </div>
          </div>
        )}

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

        {!isLoading && !isError && (
          <div className="space-y-4">
            {isElectron && (
              <SettingsSection title="Storage Locations">
                <StoragePathRow
                  label="App data location"
                  description="Database, thumbnails & search index. SSD recommended."
                  current={appDataDir}
                  pending={pendingAppDataDir}
                  onBrowse={handleChooseAppDataDir}
                  requiresRestart
                />

                <StoragePathRow
                  label="Image library location"
                  description="Original images and backups. Any drive including external storage."
                  current={imageLibraryDir}
                  pending={pendingImageLibraryDir}
                  onBrowse={handleChooseImageLibraryDir}
                  requiresRestart
                />

                {(pendingAppDataDir || pendingImageLibraryDir) && (
                  <div className="space-y-2 rounded border border-warning/30 bg-warning/5 p-3">
                    <p className="text-xs text-muted-foreground">
                      Changing a path does not move your files. Move them manually before
                      restarting.
                    </p>
                    <button
                      type="button"
                      onClick={handleApplyStorageChange}
                      className="text-xs font-medium text-primary hover:underline"
                    >
                      Restart Now to Apply
                    </button>
                  </div>
                )}
              </SettingsSection>
            )}
            <SettingsSection title="AI Model">
              <p className="text-xs text-muted-foreground">
                Active model:{' '}
                <span className="font-medium text-foreground">
                  {settings?.active_model || '(auto-detecting)'}
                </span>
              </p>

              {modelsLoading && <p className="text-xs text-muted-foreground">Loading models…</p>}
              {modelsError && <p className="text-xs text-destructive">Could not load model list</p>}
              {modelsData && modelsData.models.length > 0 && (
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 mt-2">
                  {modelsData.models.map((model) => {
                    const isActive = model.active
                    const isPending = pendingModel === model.name
                    const hwBadge =
                      HARDWARE_BADGE[model.recommended_hardware] ?? HARDWARE_BADGE['any']

                    return (
                      <button
                        key={model.name}
                        type="button"
                        onClick={() => {
                          if (isActive) return
                          if (isPending) {
                            switchModelMutation.mutate(model.name)
                          } else {
                            handleModelSelect(model.name)
                          }
                        }}
                        className={`relative text-left rounded-lg border p-3 space-y-1.5 transition-colors ${
                          isActive
                            ? 'border-primary bg-primary/5 cursor-default'
                            : isPending
                              ? 'border-warning bg-warning/10 hover:bg-warning/15'
                              : 'border-border bg-card hover:border-border/80 hover:bg-accent/30'
                        }`}
                      >
                        {isActive && (
                          <span className="absolute top-2 right-2 text-primary">
                            <Check className="h-3.5 w-3.5" />
                          </span>
                        )}

                        <div className="flex items-center gap-1.5 flex-wrap">
                          <span className="font-medium text-xs">{model.label}</span>
                          <span
                            className={`text-3xs font-medium px-1 py-0.5 rounded ${hueColor(hwBadge.hue).bg} ${hueColor(hwBadge.hue).text}`}
                          >
                            {hwBadge.label}
                          </span>
                          {!model.downloaded && (
                            <span className="text-3xs font-medium px-1 py-0.5 rounded bg-muted text-muted-foreground">
                              Not downloaded
                            </span>
                          )}
                        </div>

                        <p className="text-2xs text-muted-foreground leading-relaxed">
                          {model.description}
                        </p>

                        <p className="text-3xs text-muted-foreground">~{model.approx_size_mb} MB</p>
                      </button>
                    )
                  })}
                </div>
              )}

              {pendingModel && (
                <div className="rounded-md border p-3 text-xs space-y-2 border-border bg-muted/50">
                  <p className="text-muted-foreground">
                    Switching models will re-process all images. This can take a while.
                  </p>
                  {activeImportCount > 0 && (
                    <p className="text-muted-foreground">
                      {activeImportCount === 1 ? 'The import' : `The ${activeImportCount} imports`}{' '}
                      in progress will pause while the model changes, then carry on.
                    </p>
                  )}
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

              {modelsData && modelsData.models.some((m) => !m.active && m.downloaded) && (
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
                            disabled={
                              deleteEmbeddingsMutation.isPending &&
                              deleteEmbeddingsMutation.variables === model.name
                            }
                            className="text-xs text-destructive hover:underline disabled:opacity-50"
                          >
                            Delete embeddings
                          </button>
                        </div>
                      ))}
                  </div>
                </div>
              )}
            </SettingsSection>

            <SettingsSection title="General">
              <SettingRow
                label="Grid detection"
                description="Automatically detect grids on imported battlemaps"
              >
                <ToggleSwitch
                  label="Toggle grid detection"
                  checked={!!val('enable_image_grid_detection')}
                  onChange={(v) => setField('enable_image_grid_detection', v)}
                />
              </SettingRow>

              {!!val('enable_image_grid_detection') && (
                <SettingRow
                  label="Grid analysis resolution"
                  description="Full resolution finds thin grid lines on high-resolution maps. A limit is faster but can miss them."
                >
                  <SegmentedControl
                    options={GRID_RESOLUTION_OPTIONS}
                    value={(val('grid_analysis_max_dim') as number) ?? 0}
                    onChange={(v) => setField('grid_analysis_max_dim', v)}
                    label="Grid analysis resolution"
                  />
                </SettingRow>
              )}
            </SettingsSection>

            <TagPacksSection dialogOpen={dialogOpen} />

            <SettingsSection title="Import Limits">
              <SettingRow
                label="Max file size"
                description="Maximum size for individual image files"
              >
                <NumberSetting
                  min={1}
                  max={1000}
                  inputMode="decimal"
                  unit="MB"
                  value={formatSizeInput(val('max_import_file_size'))}
                  onChange={(v) => setField('max_import_file_size', parseSizeInput(v))}
                  ariaLabel="Max file size in MB"
                />
              </SettingRow>

              <SettingRow label="Max video size" description="Maximum size for video files">
                <NumberSetting
                  min={1}
                  max={5000}
                  inputMode="decimal"
                  unit="MB"
                  value={formatSizeInput(val('max_video_file_size'))}
                  onChange={(v) => setField('max_video_file_size', parseSizeInput(v))}
                  ariaLabel="Max video size in MB"
                />
              </SettingRow>

              <SettingRow
                label="Max files per zip"
                description="Maximum number of files expanded from one zip archive"
              >
                <NumberSetting
                  min={1}
                  max={10000}
                  inputMode="numeric"
                  value={val('max_import_files') ?? ''}
                  onChange={(v) => setField('max_import_files', parseIntInput(v))}
                  ariaLabel="Max files per zip"
                />
              </SettingRow>

              <SettingRow
                label="Max zip size (uncompressed)"
                description="Maximum total uncompressed size of one zip archive"
              >
                <NumberSetting
                  min={1}
                  max={50000}
                  inputMode="decimal"
                  unit="MB"
                  value={formatSizeInput(val('max_import_total_size'))}
                  onChange={(v) => setField('max_import_total_size', parseSizeInput(v))}
                  ariaLabel="Max zip size in MB"
                />
              </SettingRow>

              <SettingRow
                label="Stored format"
                description="Format new imports are kept in. Files already in that format, animations, and very large images stay as uploaded."
              >
                <SegmentedControl
                  options={STORED_FORMAT_OPTIONS}
                  value={(val('stored_format') as string) ?? 'original'}
                  onChange={(v) => setField('stored_format', v)}
                  label="Stored format"
                />
              </SettingRow>

              {(val('stored_format') === 'webp' || val('stored_format') === 'jpeg') && (
                <SettingRow
                  label="Quality"
                  description="For lossy WebP and JPEG (1-100). JPEG sources always use this."
                >
                  <NumberSetting
                    min={1}
                    max={100}
                    inputMode="numeric"
                    widthClass="w-16"
                    value={val('stored_quality') ?? ''}
                    onChange={(v) => setField('stored_quality', parseIntInput(v))}
                    ariaLabel="Stored quality (1-100)"
                  />
                </SettingRow>
              )}

              {val('stored_format') === 'webp' && (
                <SettingRow
                  label="Lossless WebP for PNGs"
                  description="Keeps PNGs pixel-perfect but imports more slowly. Off uses the quality above."
                >
                  <ToggleSwitch
                    label="Toggle lossless WebP"
                    checked={!!val('stored_lossless')}
                    onChange={(v) => setField('stored_lossless', v)}
                  />
                </SettingRow>
              )}
            </SettingsSection>

            <SettingsSection title="Performance" divider={false}>
              <SettingRow
                label="Parallel image processing"
                description="Images prepared at once across all imports: hashing, thumbnails, colours and grid detection (1-16)"
                requiresRestart={true}
              >
                <NumberSetting
                  min={1}
                  max={16}
                  inputMode="numeric"
                  widthClass="w-16"
                  value={val('max_concurrent_prepare') ?? ''}
                  onChange={(v) => setField('max_concurrent_prepare', parseIntInput(v))}
                  ariaLabel="Parallel image processing (1-16)"
                />
              </SettingRow>
            </SettingsSection>
          </div>
        )}
      </div>
    )
  },
)

SettingsTabContent.displayName = 'SettingsTabContent'
