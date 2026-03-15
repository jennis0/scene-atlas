import { useCallback, forwardRef, useImperativeHandle, useState, useEffect } from 'react'
import { AlertCircle, Check, Download } from 'lucide-react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Input } from '@/components/ui/input'
import { SettingRow } from '@/components/settings/SettingRow'
import { useSettingsDraft } from '@/hooks/useSettingsDraft'
import { tagApi } from '@/lib/api/tagApi'
import type { AppSettings, TagPack } from '@/types'

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
          className={`max-w-[180px] truncate text-xs font-mono ${changed ? 'text-primary' : 'text-muted-foreground'}`}
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
    queryKey: ['tag-packs'],
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
      queryClient.invalidateQueries({ queryKey: ['tag-packs'] })
      queryClient.invalidateQueries({ queryKey: ['tag-categories'] })
    },
    onError: (_err, packName) => {
      toast.error(`Failed to import ${packName}`)
    },
  })

  return (
    <section className="space-y-3">
      <p className="section-label mb-3">Tag Packs</p>
      <p className="text-xs text-muted-foreground -mt-1 mb-2">
        Import genre-specific tag vocabularies for auto-detection and filtering.
      </p>

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

      <div className="border-t border-border/30" />
    </section>
  )
}

function TagPackCard({
  pack,
  onImport,
  isImporting,
}: {
  pack: TagPack
  onImport: () => void
  isImporting: boolean
}) {
  return (
    <div
      className={`flex items-center justify-between gap-2 rounded border px-3 py-2.5 transition-colors ${
        pack.imported
          ? 'border-border/30 bg-muted/20'
          : 'border-border/50 bg-card hover:border-border'
      }`}
    >
      <div className="min-w-0">
        <p className="text-xs font-medium truncate">{pack.label}</p>
        <p className="text-[10px] text-muted-foreground truncate">{pack.description}</p>
        <p className="text-[10px] text-muted-foreground/60 mt-0.5">
          {pack.tag_count} tags
          {!pack.imported && pack.new_tags > 0 && (
            <span className="text-primary/70"> &middot; {pack.new_tags} new</span>
          )}
        </p>
      </div>
      <button
        type="button"
        disabled={pack.imported || isImporting}
        onClick={onImport}
        aria-label={`Import ${pack.label} tag pack`}
        className={`shrink-0 flex items-center gap-1 rounded px-2 py-1 text-xs transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary/40 ${
          pack.imported
            ? 'text-emerald-500/70 cursor-default'
            : 'border border-border/50 text-muted-foreground hover:text-foreground hover:border-border disabled:opacity-50'
        }`}
      >
        {pack.imported ? (
          <>
            <Check className="h-3 w-3" />
            <span>Added</span>
          </>
        ) : isImporting ? (
          <span>Importing…</span>
        ) : (
          <>
            <Download className="h-3 w-3" />
            <span>Import</span>
          </>
        )}
      </button>
    </div>
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

    const isElectron = typeof window !== 'undefined' && !!window.electronAPI
    const [appDataDir, setAppDataDir] = useState<string | null>(null)
    const [imageLibraryDir, setImageLibraryDir] = useState<string | null>(null)
    const [pendingAppDataDir, setPendingAppDataDir] = useState<string | null>(null)
    const [pendingImageLibraryDir, setPendingImageLibraryDir] = useState<string | null>(null)

    useEffect(() => {
      if (dialogOpen && isElectron) {
        window.electronAPI!.getAppDataDir().then(setAppDataDir)
        window.electronAPI!.getImageLibraryDir().then(setImageLibraryDir)
      }
    }, [dialogOpen, isElectron])

    const handleChooseAppDataDir = async () => {
      const chosen = await window.electronAPI?.chooseAppDataDir()
      if (chosen && chosen !== appDataDir) setPendingAppDataDir(chosen)
    }

    const handleChooseImageLibraryDir = async () => {
      const chosen = await window.electronAPI?.chooseImageLibraryDir()
      if (chosen && chosen !== imageLibraryDir) setPendingImageLibraryDir(chosen)
    }

    const handleApplyStorageChange = () => {
      if (!appDataDir || !imageLibraryDir) return // IPC hasn't loaded yet; wait
      window.electronAPI?.changeStorageDirs(
        pendingAppDataDir ?? appDataDir,
        pendingImageLibraryDir ?? imageLibraryDir,
      )
      // changeStorageDirs saves config and calls app.relaunch() — no return
    }

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
            {/* ── Storage Locations (Electron only) ───────────────────────────── */}
            {isElectron && (
              <section className="space-y-3">
                <p className="section-label mb-3">Storage Locations</p>

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
                  <div className="space-y-2 rounded border border-amber-500/20 bg-amber-500/5 p-3">
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

                <div className="border-t border-border/30" />
              </section>
            )}

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

            {/* ── Tag Packs ──────────────────────────────────────────────────── */}
            <TagPacksSection dialogOpen={dialogOpen} />

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

              <SettingRow
                label="Convert imports to WebP"
                description="Reduces file size 20–40% with no quality loss. Applies to new imports only."
              >
                <button
                  type="button"
                  onClick={() => setField('convert_to_webp', !val('convert_to_webp'))}
                  aria-label="Toggle WebP conversion"
                  aria-pressed={val('convert_to_webp') as boolean}
                  className={`h-6 w-11 rounded-full transition-colors flex items-center px-1 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary/40 ${
                    val('convert_to_webp') ? 'bg-primary' : 'bg-secondary border border-border/50'
                  }`}
                >
                  <div
                    className={`h-4 w-4 rounded-full bg-white shadow-sm transition-transform ${
                      val('convert_to_webp') ? 'translate-x-5' : 'translate-x-0'
                    }`}
                  />
                </button>
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
