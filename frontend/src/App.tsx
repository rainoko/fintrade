import { Route, Routes } from 'react-router-dom'
import AppShell from './components/layout/AppShell'
import DashboardPage from './pages/DashboardPage'
import NotFoundPage from './pages/NotFoundPage'
import PortfolioPage from './pages/PortfolioPage'
import StockDetailPage from './pages/StockDetailPage'

// Route table. Every page route nests under AppShell (MUI AppBar +
// persistent nav, see components/layout/AppShell.tsx) as a layout route, so
// the shell and its navigation are shared across the whole app and only the
// routed page content changes. See docs/architecture/Frontend.md §3 for the
// eventual page composition.
export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/portfolio" element={<PortfolioPage />} />
        <Route path="/stocks/:ticker" element={<StockDetailPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  )
}
