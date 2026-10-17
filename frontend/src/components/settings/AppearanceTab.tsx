import { useTheme, type Theme } from '@/contexts/ThemeContext'
import { PalettePicker } from '@/components/settings/PalettePicker'
import { SegmentedControl } from '@/components/settings/SegmentedControl'
import { SettingRow } from '@/components/settings/SettingRow'

const THEMES: readonly { value: Theme; label: string; title: string }[] = [
  { value: 'light', label: 'Light', title: 'Light mode' },
  { value: 'dark', label: 'Dark', title: 'Dark mode' },
]

/** Per-device display choices: saved locally and applied at once, unlike the Settings
 * tab, which edits the library's server-side settings. */
export function AppearanceTab() {
  const { theme, setTheme, palette, setPalette } = useTheme()
  return (
    <div>
      <p className="text-xs text-muted-foreground">
        Saved on this device and applied straight away.
      </p>
      <SettingRow label="Mode">
        <SegmentedControl label="Mode" options={THEMES} value={theme} onChange={setTheme} />
      </SettingRow>
      <div className="space-y-3 py-3">
        <p className="section-label">Palette</p>
        <PalettePicker value={palette} onChange={setPalette} />
      </div>
    </div>
  )
}
