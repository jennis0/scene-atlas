import React from 'react'
import ReactDOM from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ThemeProvider } from './contexts/ThemeContext'
import { applyPalette, getStoredPalette } from './lib/palette'
import { applyTextSize, getStoredTextSize } from './lib/textSize'
import { applyZoom, getZoom } from './lib/zoom'
import { watchShortWindow } from './lib/compactLayout'
import { watchContrast } from './lib/contrast'
import { applyTheme, readThemePreference, resolveTheme } from './lib/theme'
import { syncPrefsWithDesktop } from './lib/prefsStorage'
import { TagColorProvider } from './contexts/TagColorContext'
import App from './App'
// Bundled so the desktop app renders correctly offline.
import '@fontsource-variable/cinzel/wght.css'
import '@fontsource-variable/figtree/wght.css'
import '@fontsource-variable/figtree/wght-italic.css'
import '@fontsource-variable/jetbrains-mono/wght.css'
import '@fontsource-variable/newsreader/opsz.css'
import './index.css'

// Desktop: the app config's display choices win over this origin's localStorage
syncPrefsWithDesktop()
// Apply saved display choices before first paint (default = follow the system, navy)
applyTheme(resolveTheme(readThemePreference()))
applyPalette(getStoredPalette())
applyTextSize(getStoredTextSize())
applyZoom(getZoom())
watchShortWindow()
watchContrast()

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60 * 5, // 5 minutes
      refetchOnWindowFocus: false,
    },
  },
})

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <TagColorProvider>
          <App />
        </TagColorProvider>
      </ThemeProvider>
    </QueryClientProvider>
  </React.StrictMode>,
)
