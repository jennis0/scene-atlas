import { BrowserRouter as Router, Routes, Route } from 'react-router-dom'
import { Gallery } from './pages/Gallery'
import { Search } from './pages/Search'

function App() {
  return (
    <Router>
      <div className="min-h-screen bg-background text-foreground">
        <Routes>
          <Route path="/" element={<Gallery />} />
          <Route path="/search" element={<Search />} />
        </Routes>
      </div>
    </Router>
  )
}

export default App
