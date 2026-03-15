import { useState, useEffect, useCallback } from 'react'
import { HashRouter as Router, Routes, Route } from 'react-router-dom'
import { Toaster } from 'sonner'
import { Gallery } from './pages/Gallery'
import ErrorBoundary from './components/ErrorBoundary'
import { ModelSetupScreen } from './components/setup/ModelSetupScreen'
import { modelsApi } from './lib/api/modelsApi'
import { isServer } from './lib/appMode'

function App() {
  const [modelReady, setModelReady] = useState(!isServer)
  const [checkingSetup, setCheckingSetup] = useState(isServer)

  useEffect(() => {
    if (!isServer) {
      return
    }
    modelsApi
      .setupStatus()
      .then((status) => {
        if (!status.needs_model) setModelReady(true)
        setCheckingSetup(false)
      })
      .catch(() => {
        // If backend isn't up yet or check fails, assume model is ready (don't block the app)
        setModelReady(true)
        setCheckingSetup(false)
      })
  }, [])

  const handleSetupComplete = useCallback(() => setModelReady(true), [])

  if (checkingSetup) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <p className="text-muted-foreground text-sm">Loading…</p>
      </div>
    )
  }

  if (!modelReady) {
    return <ModelSetupScreen onComplete={handleSetupComplete} />
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
      <Toaster position="bottom-right" richColors />
    </ErrorBoundary>
  )
}

export default App
