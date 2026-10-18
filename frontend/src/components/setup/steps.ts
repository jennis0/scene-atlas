import type { SetupStatus } from '@/lib/api/modelsApi'

export type StepId = 'appearance' | 'format' | 'tag-packs' | 'model'

export const STEP_LABELS: Record<StepId, string> = {
  appearance: 'Appearance',
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

/** The steps to show: the full first run, or just the model once setup is done but the
 * model is missing (design/first-run.md). */
export function setupSteps(status: SetupStatus): StepId[] {
  if (status.setup_completed) return ['model']
  const steps: StepId[] = ['appearance', 'format', 'tag-packs']
  if (status.needs_model) steps.push('model')
  return steps
}
