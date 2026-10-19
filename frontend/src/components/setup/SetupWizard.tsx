import { useCallback, useMemo, useState } from 'react'
import { modelsApi, type SetupStatus } from '@/lib/api/modelsApi'
import { AppearanceStep } from './AppearanceStep'
import { LibraryStep } from './LibraryStep'
import { ModelStep } from './ModelStep'
import { StoredFormatStep } from './StoredFormatStep'
import { TagPackStep } from './TagPackStep'
import { setupSteps, type StepNav } from './steps'

interface SetupWizardProps {
  status: SetupStatus
  onComplete: () => void
}

/** First-run setup, the same in the desktop app and on a server, except that the desktop
 * app also chooses the library's folders. */
export function SetupWizard({ status, onComplete }: SetupWizardProps) {
  const steps = useMemo(() => setupSteps(status, window.electronAPI), [status])
  const [index, setIndex] = useState(0)
  // Kept here so Back to the tag-pack step shows what was chosen, even nothing
  const [chosenPacks, setChosenPacks] = useState<string[] | null>(null)

  const finish = useCallback(async () => {
    try {
      await modelsApi.setupComplete()
    } catch {
      // Best effort: the wizard shows again next time rather than blocking the user now
    }
    onComplete()
  }, [onComplete])

  const nav: StepNav = {
    steps,
    index,
    onBack: index > 0 ? () => setIndex(index - 1) : undefined,
    onNext: index < steps.length - 1 ? () => setIndex(index + 1) : () => void finish(),
  }

  switch (steps[index]) {
    case 'appearance':
      return <AppearanceStep nav={nav} />
    case 'library':
      return <LibraryStep nav={nav} />
    case 'format':
      return <StoredFormatStep nav={nav} />
    case 'tag-packs':
      return <TagPackStep nav={nav} chosen={chosenPacks} onChosen={setChosenPacks} />
    case 'model':
      return <ModelStep nav={nav} status={status} />
  }
}
