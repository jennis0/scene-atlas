import { BrowserRouter as Router, Routes, Route } from 'react-router-dom'
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
    </ErrorBoundary>
  )
}

export default App
