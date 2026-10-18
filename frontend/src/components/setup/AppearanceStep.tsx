import { AppearanceControls } from '@/components/settings/AppearanceControls'
import { SetupFrame } from './SetupFrame'
import type { StepNav } from './steps'

/** First step: theme and accessibility, so the rest of setup already suits the user. */
export function AppearanceStep({ nav }: { nav: StepNav }) {
  return (
    <SetupFrame
      nav={nav}
      title="Welcome. First, make it comfortable"
      description="Choose a look and text size that suit you. Changes apply straight away and are saved on this device; you can change them any time from the gear icon."
    >
      <div className="rounded-lg border border-border/50 bg-card p-4 sm:p-5 space-y-4">
        <AppearanceControls />
      </div>
    </SetupFrame>
  )
}
