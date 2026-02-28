import React from 'react'
import ReactDOM from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ThemeProvider } from './contexts/ThemeContext'
import { TagColorProvider } from './contexts/TagColorContext'
import { DesktopGate } from './components/DesktopGate'
import App from './App'
import './index.css'

// Apply saved theme before first paint (default = dark)
if (localStorage.getItem('scene-atlas-theme') !== 'light') {
  document.documentElement.classList.add('dark')
}

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
          <DesktopGate>
            <App />
          </DesktopGate>
        </TagColorProvider>
      </ThemeProvider>
    </QueryClientProvider>
  </React.StrictMode>,
)
