import { createContext, useContext, useState, useCallback, useEffect, useMemo } from 'react'
import { compactHeaderChoice, type CompactHeader } from '@/lib/compactLayout'
import { contrastChoice, useHighContrast, type Contrast } from '@/lib/contrast'
import type { DisplayChoice } from '@/lib/displayChoice'
import { paletteChoice, type Palette } from '@/lib/palette'
import { textSizeChoice, type TextSize } from '@/lib/textSize'
import { reportWindowColors } from '@/lib/windowColors'
import {
  applyTheme,
  readThemePreference,
  resolveTheme,
  saveThemePreference,
  watchSystemTheme,
  type Theme,
  type ThemePreference,
} from '@/lib/theme'

export type { Theme, ThemePreference }

interface ThemeContextValue {
  /** The theme in effect: the preference, with System resolved */
  theme: Theme
  themePreference: ThemePreference
  setThemePreference: (preference: ThemePreference) => void
  /** Switch to an explicit light or dark, the opposite of what's showing */
  toggleTheme: () => void
  palette: Palette
  setPalette: (palette: Palette) => void
  textSize: TextSize
  setTextSize: (size: TextSize) => void
  compactHeader: CompactHeader
  setCompactHeader: (value: CompactHeader) => void
  contrast: Contrast
  setContrast: (value: Contrast) => void
}

const ThemeContext = createContext<ThemeContextValue>({
  theme: 'dark',
  themePreference: 'system',
  setThemePreference: () => {},
  toggleTheme: () => {},
  palette: 'navy',
  setPalette: () => {},
  textSize: 'default',
  setTextSize: () => {},
  compactHeader: 'auto',
  setCompactHeader: () => {},
  contrast: 'auto',
  setContrast: () => {},
})

/** State for a per-device display choice: setting it saves and applies it at once. */
function useDisplayChoice<T extends string>(choice: DisplayChoice<T>) {
  const [value, setValue] = useState<T>(choice.read)
  const set = useCallback(
    (next: T) => {
      choice.save(next)
      setValue(next)
    },
    [choice],
  )
  return [value, set] as const
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [themePreference, setPreferenceState] = useState<ThemePreference>(readThemePreference)
  const [theme, setThemeState] = useState<Theme>(() => resolveTheme(themePreference))

  const setThemePreference = useCallback((next: ThemePreference) => {
    saveThemePreference(next)
    setPreferenceState(next)
    const resolved = resolveTheme(next)
    applyTheme(resolved)
    setThemeState(resolved)
  }, [])

  // System follows the OS setting while the app is open
  useEffect(() => {
    if (themePreference !== 'system') return
    return watchSystemTheme(() => {
      const resolved = resolveTheme('system')
      applyTheme(resolved)
      setThemeState(resolved)
    })
  }, [themePreference])

  const toggleTheme = useCallback(
    () => setThemePreference(theme === 'dark' ? 'light' : 'dark'),
    [theme, setThemePreference],
  )

  const [palette, setPalette] = useDisplayChoice(paletteChoice)
  const [textSize, setTextSize] = useDisplayChoice(textSizeChoice)
  const [compactHeader, setCompactHeader] = useDisplayChoice(compactHeaderChoice)
  const [contrast, setContrast] = useDisplayChoice(contrastChoice)

  // Desktop: the window background and title bar follow the colours actually in effect
  const highContrast = useHighContrast()
  useEffect(() => {
    reportWindowColors()
  }, [theme, palette, highContrast])

  const value = useMemo(
    () => ({
      theme,
      themePreference,
      setThemePreference,
      toggleTheme,
      palette,
      setPalette,
      textSize,
      setTextSize,
      compactHeader,
      setCompactHeader,
      contrast,
      setContrast,
    }),
    [
      theme,
      themePreference,
      setThemePreference,
      toggleTheme,
      palette,
      setPalette,
      textSize,
      setTextSize,
      compactHeader,
      setCompactHeader,
      contrast,
      setContrast,
    ],
  )

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components -- context hook intentionally co-exported with provider
export function useTheme(): ThemeContextValue {
  return useContext(ThemeContext)
}
