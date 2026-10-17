import { useState, useEffect } from 'react'
import { Check } from 'lucide-react'
import { toast } from 'sonner'
import { tagApi } from '@/lib/api/tagApi'
import type { TagPack } from '@/types'

interface TagPackSetupStepProps {
  /** Current model download progress message, shown in the status bar */
  modelProgressMessage: string | null
  /** Current model download progress percentage (0-100), null = indeterminate */
  modelProgressPct: number | null
  modelComplete: boolean
  onComplete: () => void
}

/**
 * Setup wizard step for selecting genre tag packs.
 *
 * Shown immediately after the user picks a model, while the model download
 * runs in the background. The model download status is displayed as a
 * subtle progress bar at the top.
 */
export function TagPackSetupStep({
  modelProgressMessage,
  modelProgressPct,
  modelComplete,
  onComplete,
}: TagPackSetupStepProps) {
  const [packs, setPacks] = useState<TagPack[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [importing, setImporting] = useState(false)
  const [importDone, setImportDone] = useState(false)
  const [fetchError, setFetchError] = useState(false)

  const fetchPacks = () => {
    setLoading(true)
    setFetchError(false)
    tagApi
      .getTagPacks()
      .then((data) => {
        setPacks(data)
        // Pre-select non-imported packs (common is already imported)
        const initial = new Set<string>()
        for (const p of data) {
          if (!p.imported) {
            initial.add(p.name)
          }
        }
        setSelected(initial)
        setLoading(false)
      })
      .catch(() => {
        setFetchError(true)
        setLoading(false)
      })
  }

  useEffect(() => {
    fetchPacks()
  }, [])

  const togglePack = (name: string) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(name)) {
        next.delete(name)
      } else {
        next.add(name)
      }
      return next
    })
  }

  const handleContinue = async () => {
    const toImport = [...selected]
    if (toImport.length === 0) {
      setImportDone(true)
      return
    }

    setImporting(true)
    try {
      await tagApi.importMultipleTagPacks(toImport)
    } catch {
      toast.error('Some tag packs failed to import. You can retry from Settings later.')
    }
    setImporting(false)
    setImportDone(true)
  }

  // When both import is done and model is complete, finish setup
  useEffect(() => {
    if (importDone && modelComplete) {
      onComplete()
    }
  }, [importDone, modelComplete, onComplete])

  return (
    <div className="min-h-screen bg-background flex items-center justify-center p-6">
      <div className="w-full max-w-2xl space-y-6">
        <div className="space-y-1.5">
          {!modelComplete && (
            <>
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                <span>{modelProgressMessage ?? 'Setting up AI model...'}</span>
                {modelProgressPct != null && modelProgressPct > 0 && (
                  <span>{modelProgressPct}%</span>
                )}
              </div>
              <div className="w-full h-1 bg-muted rounded-full overflow-hidden">
                {modelProgressPct != null && modelProgressPct > 0 ? (
                  <div
                    className="h-full bg-primary/60 rounded-full transition-all duration-500"
                    style={{ width: `${modelProgressPct}%` }}
                  />
                ) : (
                  <div className="h-full bg-primary/60 rounded-full animate-pulse w-1/3" />
                )}
              </div>
            </>
          )}
          {modelComplete && (
            <div className="flex items-center gap-1.5 text-xs text-emerald-600 dark:text-emerald-400">
              <Check className="h-3 w-3" />
              <span>AI model ready</span>
            </div>
          )}
        </div>

        <div className="text-center space-y-2">
          <h1 className="text-2xl font-bold">Choose Your Tag Packs</h1>
          <p className="text-muted-foreground text-sm">
            Tag packs add genre-specific vocabularies for auto-detection and filtering. You can add
            more later in Settings.
          </p>
        </div>

        {loading && (
          <div className="grid grid-cols-2 gap-3">
            {[...Array(6)].map((_, i) => (
              <div key={i} className="h-20 bg-muted/40 rounded animate-pulse" />
            ))}
          </div>
        )}

        {fetchError && !loading && !packs && (
          <div className="text-center space-y-3 py-6">
            <p className="text-sm text-destructive">
              Failed to load tag packs. Please check your connection and try again.
            </p>
            <button
              type="button"
              onClick={fetchPacks}
              className="px-4 py-2 rounded-lg border border-border text-sm font-medium hover:bg-muted transition-colors"
            >
              Retry
            </button>
          </div>
        )}

        {packs && (
          <div className="grid grid-cols-2 gap-3">
            {packs.map((pack) => {
              const isCommon = pack.imported
              const isSelected = selected.has(pack.name)

              return (
                <button
                  key={pack.name}
                  type="button"
                  disabled={isCommon || importing}
                  onClick={() => togglePack(pack.name)}
                  className={`relative text-left rounded-lg border p-3 space-y-1 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 ${
                    isCommon
                      ? 'border-border/30 bg-muted/20 cursor-default'
                      : isSelected
                        ? 'border-primary bg-primary/5'
                        : 'border-border/50 bg-card hover:border-border'
                  }`}
                >
                  <div className="flex items-start gap-2.5">
                    <div
                      className={`mt-0.5 shrink-0 h-4 w-4 rounded border flex items-center justify-center transition-colors ${
                        isCommon || isSelected
                          ? 'bg-primary border-primary'
                          : 'border-border/70 bg-background'
                      }`}
                    >
                      {(isCommon || isSelected) && (
                        <Check className="h-3 w-3 text-primary-foreground" />
                      )}
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium truncate">
                        {pack.label}
                        {isCommon && (
                          <span className="ml-1.5 text-[10px] font-normal text-muted-foreground">
                            (included)
                          </span>
                        )}
                      </p>
                      <p className="text-xs text-muted-foreground leading-relaxed mt-0.5">
                        {pack.description}
                      </p>
                      <p className="text-[10px] text-muted-foreground/60 mt-1">
                        {pack.tag_count} tags
                      </p>
                    </div>
                  </div>
                </button>
              )
            })}
          </div>
        )}

        <div className="flex flex-col items-center gap-2">
          {importDone && !modelComplete ? (
            <>
              <p className="text-sm text-muted-foreground">Waiting for model setup to finish...</p>
              <div className="w-48 h-1.5 bg-muted rounded-full overflow-hidden">
                {modelProgressPct != null && modelProgressPct > 0 ? (
                  <div
                    className="h-full bg-primary rounded-full transition-all duration-500"
                    style={{ width: `${modelProgressPct}%` }}
                  />
                ) : (
                  <div className="h-full bg-primary rounded-full animate-pulse w-1/3" />
                )}
              </div>
            </>
          ) : (
            <>
              <button
                type="button"
                onClick={handleContinue}
                disabled={importing}
                className="px-6 py-2.5 rounded-lg bg-primary text-primary-foreground font-medium text-sm hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                {importing ? 'Importing...' : 'Continue'}
              </button>
              <button
                type="button"
                onClick={() => {
                  setImportDone(true)
                }}
                disabled={importing}
                className="text-sm text-muted-foreground hover:text-foreground transition-colors"
              >
                Skip for now
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
