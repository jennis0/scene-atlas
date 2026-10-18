import type { ReactNode } from 'react'
import { useTheme } from '@/contexts/ThemeContext'
import { PalettePicker } from '@/components/settings/PalettePicker'
import { SegmentedControl } from '@/components/settings/SegmentedControl'
import { SettingRow } from '@/components/settings/SettingRow'
import { SettingsSection } from '@/components/settings/SettingsSection'
import { THEME_OPTIONS } from '@/lib/theme'
import { TEXT_SIZES } from '@/lib/textSize'
import { CONTRAST_OPTIONS } from '@/lib/contrast'

/** Theme and accessibility choices, shared by Settings → Appearance and the setup wizard.
 * Each applies at once and is saved on this device. *children* adds rows to the
 * Accessibility section. */
export function AppearanceControls({ children }: { children?: ReactNode }) {
  const {
    themePreference,
    setThemePreference,
    palette,
    setPalette,
    textSize,
    setTextSize,
    contrast,
    setContrast,
  } = useTheme()
  return (
    <>
      <SettingsSection title="Theme">
        <SettingRow label="Mode" description="System follows your computer's setting." stacked>
          <SegmentedControl
            label="Mode"
            options={THEME_OPTIONS}
            value={themePreference}
            onChange={setThemePreference}
          />
        </SettingRow>
        <SettingRow label="Palette" stacked>
          <div className="self-stretch">
            <PalettePicker value={palette} onChange={setPalette} />
          </div>
        </SettingRow>
      </SettingsSection>

      <SettingsSection title="Accessibility" divider={false}>
        <SettingRow
          label="Text size"
          description="Makes text and controls bigger; images stay the same."
          stacked
        >
          <SegmentedControl
            label="Text size"
            options={TEXT_SIZES}
            value={textSize}
            onChange={setTextSize}
          />
        </SettingRow>
        <SettingRow
          label="Contrast"
          description="Bolder text and outlines. Auto follows your system."
          stacked
        >
          <SegmentedControl
            label="Contrast"
            options={CONTRAST_OPTIONS}
            value={contrast}
            onChange={setContrast}
          />
        </SettingRow>
        {children}
      </SettingsSection>
    </>
  )
}
