import type { SetupStatus } from '@/lib/api/modelsApi'

export type StepId = 'appearance' | 'library' | 'format' | 'tag-packs' | 'model'

export const STEP_LABELS: Record<StepId, string> = {
  appearance: 'Appearance',
  library: 'Your library',
  format: 'Stored format',
  'tag-packs': 'Tag packs',
  model: 'Search model',
}

/** Where a step sits in the wizard, and how to leave it. */
export interface StepNav {
  steps: readonly StepId[]
  index: number
  /** Absent on the first step */
  onBack?: () => void
  /** Go to the next step, or finish setup on the last */
  onNext: () => void
}

/**
 * The steps to show: the full first run, or just the model once setup is done but the
 * model is missing (design/first-run.md).
 *
 * The library step is desktop only (*desktop* is window.electronAPI) and comes before
 * every step that saves to the backend, because choosing other folders swaps the database.
 * Once the desktop app reports the library chosen, the wizard is resuming after that swap
 * (the backend restarted and the page reloaded), so Appearance and the library step are
 * skipped (design/library-setup.md §2.2).
 */
export function setupSteps(status: SetupStatus, desktop?: { libraryChosen: boolean }): StepId[] {
  if (status.setup_completed) return ['model']
  const steps: StepId[] = []
  if (!desktop) steps.push('appearance')
  else if (!desktop.libraryChosen) steps.push('appearance', 'library')
  steps.push('format', 'tag-packs')
  if (status.needs_model) steps.push('model')
  return steps
}
