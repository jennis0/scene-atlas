import { AppearanceControls } from '@/components/settings/AppearanceControls'
import { SettingsSection } from '@/components/settings/SettingsSection'
import { UpdateChoiceRow } from '@/components/settings/UpdateChoiceRow'
import { useAppUpdates } from '@/hooks/useAppUpdates'
import { SetupFrame } from './SetupFrame'
import type { StepNav } from './steps'

/** First step: theme and accessibility, so the rest of setup already suits the user. In
 * the desktop app also how it updates, chosen before it first contacts GitHub. */
export function AppearanceStep({ nav }: { nav: StepNav }) {
  const { state: updates, setChoice } = useAppUpdates()
  return (
    <SetupFrame
      nav={nav}
      title="Welcome to Scene Atlas"
      description={
        updates
          ? 'Choose a look and text size that suit you, and how Scene Atlas updates. You can change them any time from the gear icon.'
          : 'Choose a look and text size that suit you. You can change them any time from the gear icon.'
      }
    >
      <div className="rounded-lg border border-border/50 bg-card p-4 sm:p-5 space-y-4">
        <AppearanceControls />
        {updates && (
          <SettingsSection title="Updates">
            <UpdateChoiceRow state={updates} onChange={setChoice} />
          </SettingsSection>
        )}
      </div>
    </SetupFrame>
  )
}
