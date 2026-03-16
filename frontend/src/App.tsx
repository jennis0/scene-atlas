import { useState, useEffect, useCallback } from 'react'
import { HashRouter as Router, Routes, Route } from 'react-router-dom'
import { Toaster } from 'sonner'
import { Gallery } from './pages/Gallery'
import ErrorBoundary from './components/ErrorBoundary'
import { ModelSetupScreen } from './components/setup/ModelSetupScreen'
import { modelsApi } from './lib/api/modelsApi'
import { isServer } from './lib/appMode'

function App() {
  const [setupReady, setSetupReady] = useState(!isServer)
  const [checkingSetup, setCheckingSetup] = useState(isServer)
  const [skipModel, setSkipModel] = useState(false)

  useEffect(() => {
    if (!isServer) {
      return
    }
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
        // If backend isn't up yet or check fails, assume setup is done (don't block the app)
        setSetupReady(true)
        setCheckingSetup(false)
      })
  }, [])

  const handleSetupComplete = useCallback(() => setSetupReady(true), [])

  if (checkingSetup) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <p className="text-muted-foreground text-sm">Loading...</p>
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
      <Toaster position="bottom-right" richColors />
    </ErrorBoundary>
  )
}

export default App
