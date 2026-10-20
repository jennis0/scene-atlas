import type { AppUpdateState, UpdateChoice } from '@/electron'
import { SegmentedControl } from './SegmentedControl'
import { SettingRow } from './SettingRow'

const CHOICES: readonly { value: UpdateChoice; label: string; title: string }[] = [
  {
    value: 'automatic',
    label: 'Automatic',
    title: 'Download new versions and install them when you restart',
  },
  { value: 'ask', label: 'Ask first', title: 'Say when a new version is out' },
  { value: 'off', label: 'Off', title: "Don't check for new versions" },
]

const DESCRIPTIONS: Record<UpdateChoice, string> = {
  automatic: 'Downloads new versions and installs them when you restart.',
  ask: 'Tells you when a new version is out. Nothing installs until you choose.',
  off: 'Only checks when you press Check now.',
}

/** How the desktop app updates itself (design/electron.md#updates), in Settings and the
 * setup wizard. An install that can only link to the download (macOS, .deb) has no
 * Automatic. */
export function UpdateChoiceRow({
  state,
  onChange,
}: {
  state: AppUpdateState
  onChange: (choice: UpdateChoice) => void
}) {
  const canInstall = state.mode === 'install'
  const options = canInstall ? CHOICES : CHOICES.filter((c) => c.value !== 'automatic')
  const value = !canInstall && state.choice === 'automatic' ? 'ask' : state.choice
  return (
    <SettingRow label="New versions" description={DESCRIPTIONS[value]} stacked>
      <SegmentedControl label="New versions" options={options} value={value} onChange={onChange} />
    </SettingRow>
  )
}
