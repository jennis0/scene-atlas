import { useEffect, useState } from 'react'
import { settingsApi } from '@/lib/api/settingsApi'
import { getApiErrorMessage } from '@/lib/getErrorMessage'
import type { AppSettings } from '@/types'
import { ChoiceCard } from './ChoiceCard'
import { SetupFrame } from './SetupFrame'
import type { StepNav } from './steps'

type Choice = 'original' | 'webp'

const CHOICES: readonly { value: Choice; label: string; description: string }[] = [
  {
    value: 'original',
    label: 'Keep files as they are',
    description: 'Every image is stored exactly as you import it.',
  },
  {
    value: 'webp',
    label: 'Convert to WebP',
    description:
      'Smaller files. PNGs stay pixel-perfect; JPEGs are re-compressed at high quality. The library keeps only the converted file.',
  },
]

/** The library's stored format (`stored_format`). Only Original and WebP are offered here;
 * Settings has JPEG, PNG and the quality options. On a server, CONVERT_TO_WEBP=1 only
 * changes the starting choice. */
export function StoredFormatStep({ nav }: { nav: StepNav }) {
  const [saved, setSaved] = useState<AppSettings['stored_format'] | null>(null)
  const [choice, setChoice] = useState<Choice>('original')
  const [loadFailed, setLoadFailed] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    settingsApi
      .get()
      .then((settings) => {
        setSaved(settings.stored_format)
        setChoice(settings.stored_format === 'webp' ? 'webp' : 'original')
      })
      .catch(() => setLoadFailed(true))
  }, [])

  const handleContinue = async () => {
    if (saved === choice) {
      nav.onNext()
      return
    }
    setSaving(true)
    setError(null)
    try {
      await settingsApi.patch({ stored_format: choice })
      setSaved(choice)
      nav.onNext()
    } catch (err) {
      setError(getApiErrorMessage(err, 'Could not save the stored format.'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <SetupFrame
      nav={nav}
      title="How should imported images be stored?"
      description="Scene Atlas keeps its own copy of everything you import; the files you import from are never changed. This applies to new imports, and you can change it later in Settings."
      primary={{
        onClick: handleContinue,
        busy: saving,
        disabled: saved === null && !loadFailed,
      }}
      error={
        error ??
        (loadFailed ? 'Could not load the current setting. Continuing keeps the default.' : null)
      }
    >
      <div
        role="radiogroup"
        aria-label="Stored format"
        className="grid grid-cols-1 sm:grid-cols-2 gap-3"
      >
        {CHOICES.map((option) => (
          <ChoiceCard
            key={option.value}
            name="setup-stored-format"
            choice={{ ...option, description: <p>{option.description}</p> }}
            checked={choice === option.value}
            onSelect={() => setChoice(option.value)}
          />
        ))}
      </div>
    </SetupFrame>
  )
}
