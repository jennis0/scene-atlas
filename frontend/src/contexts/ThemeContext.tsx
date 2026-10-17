import { createContext, useContext, useState, useCallback, useMemo } from 'react'
import { getStoredPalette, savePalette, type Palette } from '@/lib/palette'
import { getStoredTextSize, saveTextSize, type TextSize } from '@/lib/textSize'

export type Theme = 'light' | 'dark'

interface ThemeContextValue {
  theme: Theme
  setTheme: (theme: Theme) => void
  toggleTheme: () => void
  palette: Palette
  setPalette: (palette: Palette) => void
  textSize: TextSize
  setTextSize: (size: TextSize) => void
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
})

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

  const [palette, setPaletteState] = useState<Palette>(getStoredPalette)
  const setPalette = useCallback((next: Palette) => {
    savePalette(next)
    setPaletteState(next)
  }, [])

  const [textSize, setTextSizeState] = useState<TextSize>(getStoredTextSize)
  const setTextSize = useCallback((next: TextSize) => {
    saveTextSize(next)
    setTextSizeState(next)
  }, [])

  const value = useMemo(
    () => ({ theme, setTheme, toggleTheme, palette, setPalette, textSize, setTextSize }),
    [theme, setTheme, toggleTheme, palette, setPalette, textSize, setTextSize],
  )

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components -- context hook intentionally co-exported with provider
export function useTheme(): ThemeContextValue {
  return useContext(ThemeContext)
}
