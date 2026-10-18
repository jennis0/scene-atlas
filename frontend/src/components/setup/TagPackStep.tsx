import { useCallback, useEffect, useState } from 'react'
import { Check } from 'lucide-react'
import { tagApi } from '@/lib/api/tagApi'
import { getApiErrorMessage } from '@/lib/getErrorMessage'
import type { TagPack } from '@/types'
import { LoadFailed } from './LoadFailed'
import { SetupFrame } from './SetupFrame'
import type { StepNav } from './steps'

interface TagPackStepProps {
  nav: StepNav
  /** The packs chosen on an earlier visit (after Back); null the first time, which selects all */
  chosen: string[] | null
  onChosen: (packs: string[]) => void
}

/** Which tag packs the library starts with, Common included. Continue installs exactly the
 * selection (PUT /tags/packs), so it can also remove Common. */
export function TagPackStep({ nav, chosen, onChosen }: TagPackStepProps) {
  const [packs, setPacks] = useState<TagPack[] | null>(null)
  const [selected, setSelected] = useState<Set<string>>(new Set(chosen ?? []))
  const [fetchError, setFetchError] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchPacks = useCallback(() => {
    setFetchError(false)
    tagApi
      .getTagPacks()
      .then((data) => {
        setPacks(data)
        if (chosen === null) setSelected(new Set(data.map((p) => p.name)))
      })
      .catch(() => setFetchError(true))
  }, [chosen])

  useEffect(() => {
    fetchPacks()
  }, [fetchPacks])

  const togglePack = (name: string) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(name)) next.delete(name)
      else next.add(name)
      return next
    })
  }

  const handleContinue = async () => {
    const packNames = [...selected]
    setSaving(true)
    setError(null)
    try {
      await tagApi.setInstalledPacks(packNames)
      onChosen(packNames)
      nav.onNext()
    } catch (err) {
      setError(getApiErrorMessage(err, "Couldn't save the tag packs."))
      setSaving(false)
    }
  }

  return (
    <SetupFrame
      nav={nav}
      title="Choose tag packs"
      description="Tags help you filter and organise your library. These packs are ready-made sets of tags for common genres. You can add, remove or edit tags at any time."
      primary={{ onClick: handleContinue, busy: saving, disabled: !packs }}
      error={error}
    >
      {!packs && !fetchError && (
        <div role="status" aria-label="Loading tag packs" className="grid grid-cols-2 gap-3">
          {[...Array(6)].map((_, i) => (
            <div key={i} className="h-20 bg-muted/40 rounded animate-pulse" />
          ))}
        </div>
      )}

      {fetchError && !packs && (
        <LoadFailed message="Couldn't load the tag packs." onRetry={fetchPacks} />
      )}

      {packs && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {packs.map((pack) => (
            <PackToggle
              key={pack.name}
              pack={pack}
              selected={selected.has(pack.name)}
              disabled={saving}
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
  return (
    <button
      type="button"
      disabled={disabled}
      aria-pressed={selected}
      onClick={onToggle}
      className={`relative text-left rounded-lg border p-3 space-y-1 transition-colors ${
        selected ? 'border-primary bg-primary/5' : 'border-border/50 bg-card hover:border-border'
      }`}
    >
      <div className="flex items-start gap-2.5">
        <div
          aria-hidden="true"
          className={`mt-0.5 shrink-0 h-4 w-4 rounded border flex items-center justify-center transition-colors ${
            selected ? 'bg-primary border-primary' : 'border-border/70 bg-background'
          }`}
        >
          {selected && <Check className="h-3 w-3 text-primary-foreground" />}
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium">{pack.label}</p>
          <p className="text-xs text-muted-foreground leading-relaxed mt-0.5">{pack.description}</p>
          <p className="text-3xs text-muted-foreground mt-1">{pack.tag_count} tags</p>
        </div>
      </div>
    </button>
  )
}
