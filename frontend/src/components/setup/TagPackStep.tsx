import { useEffect, useState } from 'react'
import { AxiosError } from 'axios'
import { Check } from 'lucide-react'
import { tagApi } from '@/lib/api/tagApi'
import { getApiErrorMessage } from '@/lib/getErrorMessage'
import type { TagPack } from '@/types'
import { SetupFrame } from './SetupFrame'
import type { StepNav } from './steps'

function importFailureMessage(err: unknown): string {
  if (err instanceof AxiosError && err.response?.status === 429) {
    return 'Too many attempts. Wait a minute and try again.'
  }
  return getApiErrorMessage(err, 'Could not reach Scene Atlas.')
}

/** Genre tag packs to import. Common is always installed; packs not yet imported start
 * selected. Continue imports the selection; Skip moves on without importing. */
export function TagPackStep({ nav }: { nav: StepNav }) {
  const [packs, setPacks] = useState<TagPack[] | null>(null)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [fetchError, setFetchError] = useState(false)
  const [importing, setImporting] = useState(false)
  const [importErrors, setImportErrors] = useState<string[]>([])

  const fetchPacks = (keepSelection?: Set<string>) => {
    setFetchError(false)
    return tagApi
      .getTagPacks()
      .then((data) => {
        setPacks(data)
        // After a partial import, keep the user's choice for the packs that failed
        const initial = new Set<string>()
        for (const p of data) {
          if (!p.imported && (!keepSelection || keepSelection.has(p.name))) initial.add(p.name)
        }
        setSelected(initial)
      })
      .catch(() => setFetchError(true))
  }

  useEffect(() => {
    fetchPacks()
  }, [])

  const togglePack = (name: string) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(name)) next.delete(name)
      else next.add(name)
      return next
    })
  }

  const handleContinue = async () => {
    const toImport = [...selected]
    if (toImport.length === 0) {
      nav.onNext()
      return
    }
    setImporting(true)
    setImportErrors([])
    let errors: string[]
    try {
      errors = (await tagApi.importMultipleTagPacks(toImport)).errors
    } catch (err) {
      errors = [importFailureMessage(err)]
    }
    setImporting(false)
    if (errors.length > 0) {
      setImportErrors(errors)
      await fetchPacks(selected)
    } else {
      nav.onNext()
    }
  }

  return (
    <SetupFrame
      nav={nav}
      title="Add tag packs"
      description="Tag packs add tags for a genre. They're used to tag your imports automatically and to filter your library. Common tags are always included, and you can add packs later in Settings."
      onPrimary={handleContinue}
      primaryLabel={importErrors.length > 0 ? 'Try again' : undefined}
      busy={importing}
      primaryDisabled={!packs}
      secondary={
        <button
          type="button"
          onClick={nav.onNext}
          disabled={importing}
          className="text-sm text-muted-foreground hover:text-foreground transition-colors"
        >
          Skip for now
        </button>
      }
      error={
        importErrors.length > 0 ? (
          <>
            <p className="font-medium text-destructive">Some tag packs couldn't be imported</p>
            <ul className="mt-1 list-disc pl-5 text-xs text-muted-foreground">
              {importErrors.map((error) => (
                <li key={error}>{error}</li>
              ))}
            </ul>
            <p className="mt-2 text-xs text-muted-foreground">
              Try again, or skip and add them later in Settings.
            </p>
          </>
        ) : null
      }
    >
      {!packs && !fetchError && (
        <div role="status" aria-label="Loading tag packs" className="grid grid-cols-2 gap-3">
          {[...Array(6)].map((_, i) => (
            <div key={i} className="h-20 bg-muted/40 rounded animate-pulse" />
          ))}
        </div>
      )}

      {fetchError && !packs && (
        <div className="text-center space-y-3 py-6">
          <p role="alert" className="text-sm text-destructive">
            Couldn't load the tag packs.
          </p>
          <button
            type="button"
            onClick={() => fetchPacks()}
            className="px-4 py-2 rounded-lg border border-border text-sm font-medium hover:bg-muted transition-colors"
          >
            Try again
          </button>
        </div>
      )}

      {packs && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {packs.map((pack) => (
            <PackToggle
              key={pack.name}
              pack={pack}
              selected={selected.has(pack.name)}
              disabled={importing}
              onToggle={() => togglePack(pack.name)}
            />
          ))}
        </div>
      )}
    </SetupFrame>
  )
}

interface PackToggleProps {
  pack: TagPack
  selected: boolean
  disabled: boolean
  onToggle: () => void
}

function PackToggle({ pack, selected, disabled, onToggle }: PackToggleProps) {
  const included = pack.imported
  const on = included || selected
  return (
    <button
      type="button"
      disabled={included || disabled}
      aria-pressed={on}
      onClick={onToggle}
      className={`relative text-left rounded-lg border p-3 space-y-1 transition-colors ${
        included
          ? 'border-border/30 bg-muted/20 cursor-default'
          : selected
            ? 'border-primary bg-primary/5'
            : 'border-border/50 bg-card hover:border-border'
      }`}
    >
      <div className="flex items-start gap-2.5">
        <div
          aria-hidden="true"
          className={`mt-0.5 shrink-0 h-4 w-4 rounded border flex items-center justify-center transition-colors ${
            on ? 'bg-primary border-primary' : 'border-border/70 bg-background'
          }`}
        >
          {on && <Check className="h-3 w-3 text-primary-foreground" />}
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium">
            {pack.label}
            {included && (
              <span className="ml-1.5 text-3xs font-normal text-muted-foreground">
                {/* Common comes with every library; others were imported, e.g. before Back */}
                {pack.name === 'common' ? '(included)' : '(added)'}
              </span>
            )}
          </p>
          <p className="text-xs text-muted-foreground leading-relaxed mt-0.5">{pack.description}</p>
          <p className="text-3xs text-muted-foreground mt-1">{pack.tag_count} tags</p>
        </div>
      </div>
    </button>
  )
}
