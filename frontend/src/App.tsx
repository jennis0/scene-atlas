import { useState, useEffect, useCallback } from 'react'
import { HashRouter as Router, Routes, Route } from 'react-router-dom'
import { Toaster } from 'sonner'
import { Gallery } from './pages/Gallery'
import ErrorBoundary from './components/ErrorBoundary'
import { ModelSetupScreen } from './components/setup/ModelSetupScreen'
import { modelsApi } from './lib/api/modelsApi'
import { useTheme } from './contexts/ThemeContext'

function App() {
  const { theme } = useTheme()
  const [setupReady, setSetupReady] = useState(false)
  const [checkingSetup, setCheckingSetup] = useState(true)
  const [skipModel, setSkipModel] = useState(false)
  const [setupError, setSetupError] = useState(false)

  const checkSetupStatus = useCallback(() => {
    setCheckingSetup(true)
    setSetupError(false)
    modelsApi
      .setupStatus()
      .then((status) => {
        const needsSetup = status.needs_model || status.needs_tag_packs
        if (!needsSetup) {
          setSetupReady(true)
        } else {
          // If model is already configured but tag packs are needed,
          // tell the wizard to skip the model selection step.
          setSkipModel(!status.needs_model)
        }
        setCheckingSetup(false)
      })
      .catch(() => {
        setSetupError(true)
        setCheckingSetup(false)
      })
  }, [])

  useEffect(() => {
    checkSetupStatus()
  }, [checkSetupStatus])

  const handleSetupComplete = useCallback(() => setSetupReady(true), [])

  if (checkingSetup) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <p className="text-muted-foreground text-sm">Loading...</p>
      </div>
    )
  }

  if (setupError) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center p-6">
        <div className="w-full max-w-md rounded-lg border border-border bg-card p-8 text-center space-y-4 shadow-sm">
          <h2 className="text-lg font-semibold text-foreground">
            Unable to connect to Scene Atlas backend
          </h2>
          <p className="text-sm text-muted-foreground">
            The backend server may not be running or is unreachable. Please check your setup and try
            again.
          </p>
          <button
            type="button"
            onClick={checkSetupStatus}
            className="px-5 py-2 rounded-lg bg-primary text-primary-foreground font-medium text-sm hover:bg-primary/90 transition-colors"
          >
            Retry
          </button>
        </div>
      </div>
    )
  }

  if (!setupReady) {
    return <ModelSetupScreen onComplete={handleSetupComplete} skipModel={skipModel} />
  }

  return (
    <ErrorBoundary>
      <Router>
        <div className="min-h-screen bg-background text-foreground">
          <Routes>
            <Route path="/" element={<Gallery />} />
          </Routes>
        </div>
      </Router>
      <Toaster position="bottom-right" richColors theme={theme} />
    </ErrorBoundary>
  )
}

export default App
