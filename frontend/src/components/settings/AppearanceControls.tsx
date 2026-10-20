import type { ReactNode } from 'react'
import { useTheme } from '@/contexts/ThemeContext'
import { PalettePicker } from '@/components/settings/PalettePicker'
import { SegmentedControl } from '@/components/settings/SegmentedControl'
import { SettingRow } from '@/components/settings/SettingRow'
import { SettingsSection } from '@/components/settings/SettingsSection'
import { THEME_OPTIONS } from '@/lib/theme'
import { TEXT_SIZES } from '@/lib/textSize'
import { CONTRAST_OPTIONS } from '@/lib/contrast'
import { isApp } from '@/lib/appMode'
import { setZoom, useZoom, ZOOM_LEVELS } from '@/lib/zoom'

const ZOOM_OPTIONS = ZOOM_LEVELS.map((level) => ({
  value: level as number,
  label: `${level}%`,
  title: level === 100 ? 'Actual size' : `Zoom to ${level}%`,
}))

/** Theme and accessibility choices, shared by Settings → Appearance and the setup wizard.
 * Each applies at once and is saved on this device. *children* adds rows to the
 * Accessibility section. */
export function AppearanceControls({ children }: { children?: ReactNode }) {
  return (
    <>
      <ThemeSection />
      <AccessibilitySection>{children}</AccessibilitySection>
    </>
  )
}

function ThemeSection() {
  const { themePreference, setThemePreference, palette, setPalette } = useTheme()
  return (
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
  )
}

function AccessibilitySection({ children }: { children?: ReactNode }) {
  const { textSize, setTextSize, contrast, setContrast } = useTheme()
  return (
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
      {/* A browser has its own zoom */}
      {isApp && <ZoomRow />}
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
  )
}

function ZoomRow() {
  const zoom = useZoom()
  const shortcut = window.electronAPI?.platform === 'darwin' ? '⌘' : 'Ctrl'
  return (
    <SettingRow
      label="Zoom"
      description={`Makes everything bigger, images included. ${shortcut} + and ${shortcut} − also zoom.`}
      stacked
    >
      <SegmentedControl label="Zoom" options={ZOOM_OPTIONS} value={zoom} onChange={setZoom} />
    </SettingRow>
  )
}
