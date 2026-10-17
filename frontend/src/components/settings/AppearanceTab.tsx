import { useTheme, type Theme } from '@/contexts/ThemeContext'
import { PalettePicker } from '@/components/settings/PalettePicker'
import { SegmentedControl } from '@/components/settings/SegmentedControl'
import { SettingRow } from '@/components/settings/SettingRow'
import { TEXT_SIZES } from '@/lib/textSize'
import { COMPACT_HEADER_OPTIONS } from '@/lib/compactLayout'
import { CONTRAST_OPTIONS } from '@/lib/contrast'

const THEMES: readonly { value: Theme; label: string; title: string }[] = [
  { value: 'light', label: 'Light', title: 'Light mode' },
  { value: 'dark', label: 'Dark', title: 'Dark mode' },
]

/** Per-device display choices: saved locally and applied at once, unlike the Settings
 * tab, which edits the library's server-side settings. */
export function AppearanceTab() {
  const {
    theme,
    setTheme,
    palette,
    setPalette,
    textSize,
    setTextSize,
    compactHeader,
    setCompactHeader,
    contrast,
    setContrast,
  } = useTheme()
  return (
    <div>
      <p className="text-xs text-muted-foreground">Only affects this device.</p>
      <SettingRow label="Mode">
        <SegmentedControl label="Mode" options={THEMES} value={theme} onChange={setTheme} />
      </SettingRow>
      <SettingRow
        label="Contrast"
        description="Bolder text and outlines. Auto follows your system."
      >
        <SegmentedControl
          label="Contrast"
          options={CONTRAST_OPTIONS}
          value={contrast}
          onChange={setContrast}
        />
      </SettingRow>
      <SettingRow
        label="Text size"
        description="Makes text and controls bigger; images stay the same."
      >
        <SegmentedControl
          label="Text size"
          options={TEXT_SIZES}
          value={textSize}
          onChange={setTextSize}
        />
      </SettingRow>
      <SettingRow
        label="Compact header"
        description="Fits the header into two rows. Auto does this on small windows."
      >
        <SegmentedControl
          label="Compact header"
          options={COMPACT_HEADER_OPTIONS}
          value={compactHeader}
          onChange={setCompactHeader}
        />
      </SettingRow>
      <div className="space-y-3 py-3">
        <p className="section-label">Palette</p>
        <PalettePicker value={palette} onChange={setPalette} />
      </div>
    </div>
  )
}
