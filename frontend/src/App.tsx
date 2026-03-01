import { HashRouter as Router, Routes, Route } from 'react-router-dom'
import { Toaster } from 'sonner'
import { Gallery } from './pages/Gallery'
import ErrorBoundary from './components/ErrorBoundary'

function App() {
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
