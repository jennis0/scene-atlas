import { useTheme } from '@/contexts/ThemeContext'
import { AppearanceControls } from '@/components/settings/AppearanceControls'
import { SegmentedControl } from '@/components/settings/SegmentedControl'
import { SettingRow } from '@/components/settings/SettingRow'
import { COMPACT_HEADER_OPTIONS } from '@/lib/compactLayout'

/** Per-device display choices: saved locally and applied at once, unlike the Settings
 * tab, which edits the library's server-side settings. */
export function AppearanceTab() {
  const { compactHeader, setCompactHeader } = useTheme()
  return (
    <div className="space-y-4">
      <p className="text-xs text-muted-foreground">These choices only affect this device.</p>
      <AppearanceControls>
        <SettingRow
          label="Compact header"
          description="Fits the header into two rows. Auto does this on small windows."
          stacked
        >
          <SegmentedControl
            label="Compact header"
            options={COMPACT_HEADER_OPTIONS}
            value={compactHeader}
            onChange={setCompactHeader}
          />
        </SettingRow>
      </AppearanceControls>
    </div>
  )
}
