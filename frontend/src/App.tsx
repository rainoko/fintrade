import { Route, Routes } from 'react-router-dom'
import DashboardPage from './pages/DashboardPage'
import PortfolioPage from './pages/PortfolioPage'
import StockDetailPage from './pages/StockDetailPage'

// Route table. Pages are placeholders until frontend-app-shell-navigation
// (nav shell) and the page-level feature tasks land — see
// docs/architecture/Frontend.md §3 for the eventual page composition.
export default function App() {
  return (
    <Routes>
      <Route path="/" element={<DashboardPage />} />
      <Route path="/portfolio" element={<PortfolioPage />} />
      <Route path="/stocks/:ticker" element={<StockDetailPage />} />
    </Routes>
  )
}
