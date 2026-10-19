import { useState, useEffect, useCallback } from 'react'
import { HashRouter as Router, Routes, Route } from 'react-router'
import { createPortal } from 'react-dom'
import { Toaster } from 'sonner'
import { Gallery } from './pages/Gallery'
import ErrorBoundary from './components/ErrorBoundary'
import { SetupWizard } from './components/setup/SetupWizard'
import { WindowDragBar } from './components/WindowDragBar'
import { UpdateNotifier } from './components/UpdateNotifier'
import { modelsApi, type SetupStatus } from './lib/api/modelsApi'
import { useTheme } from './contexts/ThemeContext'

/** Setup is needed until the wizard is finished, or when the model is missing and isn't
 * on its way (design/first-run.md). A download in progress shows in the gallery instead. */
function needsSetup(status: SetupStatus): boolean {
  return !status.setup_completed || (status.needs_model && !status.model_activating)
}

type Gate =
  | { kind: 'checking' }
  | { kind: 'error' }
  | { kind: 'setup'; status: SetupStatus }
  | { kind: 'ready' }

function App() {
  const { theme } = useTheme()
  const [gate, setGate] = useState<Gate>({ kind: 'checking' })

  const checkSetupStatus = useCallback(() => {
    setGate({ kind: 'checking' })
    modelsApi
      .setupStatus()
      .then((status) => setGate(needsSetup(status) ? { kind: 'setup', status } : { kind: 'ready' }))
      .catch(() => setGate({ kind: 'error' }))
  }, [])

  useEffect(() => {
    checkSetupStatus()
  }, [checkSetupStatus])

  const handleSetupComplete = useCallback(() => setGate({ kind: 'ready' }), [])

  if (gate.kind === 'checking') {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <WindowDragBar />
        <p role="status" className="text-muted-foreground text-sm">
          Loading…
        </p>
      </div>
    )
  }

  if (gate.kind === 'error') {
    return (
      <>
        <WindowDragBar />
        <ConnectionError onRetry={checkSetupStatus} />
      </>
    )
  }

  if (gate.kind === 'setup') {
    return (
      <>
        <WindowDragBar />
        <SetupWizard status={gate.status} onComplete={handleSetupComplete} />
      </>
    )
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
      <UpdateNotifier />
      {/* Outside the app root so toasts stay usable while a modal inerts the page */}
      {createPortal(
        <div data-modal-exempt="">
          <Toaster position="bottom-right" richColors theme={theme} />
        </div>,
        document.body,
      )}
    </ErrorBoundary>
  )
}

function ConnectionError({ onRetry }: { onRetry: () => void }) {
  // In the desktop app the backend is ours to restart; on a server it's the operator's
  const isDesktop = typeof window !== 'undefined' && !!window.electronAPI
  return (
    <div className="min-h-screen bg-background flex items-center justify-center p-6">
      <div
        role="alert"
        className="w-full max-w-md rounded-lg border border-border bg-card p-8 text-center space-y-4 shadow-sm"
      >
        <h1 className="text-lg font-semibold text-foreground">Can't reach Scene Atlas</h1>
        <p className="text-sm text-muted-foreground">
          {isDesktop
            ? 'Scene Atlas is still starting, or has stopped. Try again, or restart Scene Atlas if this keeps happening.'
            : 'The Scene Atlas server is not responding. Check that it is running, then try again.'}
        </p>
        <button
          type="button"
          onClick={onRetry}
          className="px-5 py-2 rounded-lg bg-primary text-primary-foreground font-medium text-sm hover:bg-primary/90 transition-colors"
        >
          Try again
        </button>
      </div>
    </div>
  )
}

export default App
