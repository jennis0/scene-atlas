import { createContext, useContext, useState, useCallback, useMemo } from 'react'
import { applyPalette, getStoredPalette, PALETTE_STORAGE_KEY, type Palette } from '@/lib/palette'

export type Theme = 'light' | 'dark'

interface ThemeContextValue {
  theme: Theme
  toggleTheme: () => void
  palette: Palette
  setPalette: (palette: Palette) => void
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
  toggleTheme: () => {},
  palette: 'navy',
  setPalette: () => {},
})

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setTheme] = useState<Theme>(getStoredTheme)

  const toggleTheme = useCallback(() => {
    setTheme((prev) => {
      const next = prev === 'dark' ? 'light' : 'dark'
      try {
        localStorage.setItem(STORAGE_KEY, next)
      } catch {
        // Storage blocked (private mode, quota): the theme still applies for this session.
      }
      if (next === 'dark') {
        document.documentElement.classList.add('dark')
      } else {
        document.documentElement.classList.remove('dark')
      }
      return next
    })
  }, [])

  const [palette, setPaletteState] = useState<Palette>(getStoredPalette)
  const setPalette = useCallback((next: Palette) => {
    try {
      localStorage.setItem(PALETTE_STORAGE_KEY, next)
    } catch {
      // Storage blocked: the palette still applies for this session.
    }
    applyPalette(next)
    setPaletteState(next)
  }, [])

  const value = useMemo(
    () => ({ theme, toggleTheme, palette, setPalette }),
    [theme, toggleTheme, palette, setPalette],
  )

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components -- context hook intentionally co-exported with provider
export function useTheme(): ThemeContextValue {
  return useContext(ThemeContext)
}
