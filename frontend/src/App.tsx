import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Home from './pages/Home'
import Report from './pages/Report'
import History from './pages/History'

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/report/:id" element={<Report />} />
        <Route path="/history" element={<History />} />
      </Routes>
    </BrowserRouter>
  )
}

export default App
