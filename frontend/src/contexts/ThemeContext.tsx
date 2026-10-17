import { createContext, useContext, useState, useCallback, useMemo } from 'react'
import { compactHeaderChoice, type CompactHeader } from '@/lib/compactLayout'
import { contrastChoice, type Contrast } from '@/lib/contrast'
import type { DisplayChoice } from '@/lib/displayChoice'
import { paletteChoice, type Palette } from '@/lib/palette'
import { textSizeChoice, type TextSize } from '@/lib/textSize'

export type Theme = 'light' | 'dark'

interface ThemeContextValue {
  theme: Theme
  setTheme: (theme: Theme) => void
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

const STORAGE_KEY = 'scene-atlas-theme'

function getStoredTheme(): Theme {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    return stored === 'light' ? 'light' : 'dark'
  } catch {
    return 'dark'
  }
}

const ThemeContext = createContext<ThemeContextValue>({
  theme: 'dark',
  setTheme: () => {},
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
  const [theme, setThemeState] = useState<Theme>(getStoredTheme)

  const setTheme = useCallback((next: Theme) => {
    try {
      localStorage.setItem(STORAGE_KEY, next)
    } catch {
      // Storage blocked (private mode, quota): the theme still applies for this session.
    }
    document.documentElement.classList.toggle('dark', next === 'dark')
    setThemeState(next)
  }, [])

  const toggleTheme = useCallback(
    () => setTheme(theme === 'dark' ? 'light' : 'dark'),
    [theme, setTheme],
  )

  const [palette, setPalette] = useDisplayChoice(paletteChoice)
  const [textSize, setTextSize] = useDisplayChoice(textSizeChoice)
  const [compactHeader, setCompactHeader] = useDisplayChoice(compactHeaderChoice)
  const [contrast, setContrast] = useDisplayChoice(contrastChoice)

  const value = useMemo(
    () => ({
      theme,
      setTheme,
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
      setTheme,
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
