import React from 'react'
import ReactDOM from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ThemeProvider } from './contexts/ThemeContext'
import { applyPalette, getStoredPalette } from './lib/palette'
import { TagColorProvider } from './contexts/TagColorContext'
import App from './App'
// Bundled so the desktop app renders correctly offline.
import '@fontsource-variable/cinzel/wght.css'
import '@fontsource-variable/figtree/wght.css'
import '@fontsource-variable/figtree/wght-italic.css'
import '@fontsource-variable/jetbrains-mono/wght.css'
import '@fontsource-variable/newsreader/opsz.css'
import './index.css'

// Apply saved theme and palette before first paint (default = dark, navy)
if (localStorage.getItem('scene-atlas-theme') !== 'light') {
  document.documentElement.classList.add('dark')
}
applyPalette(getStoredPalette())

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
