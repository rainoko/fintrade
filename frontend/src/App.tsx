import { Route, Routes } from 'react-router-dom'
import AppShell from './components/layout/AppShell'
import DailyHomeworkPage from './pages/DailyHomeworkPage'
import DashboardPage from './pages/DashboardPage'
import MethodologyPage from './pages/MethodologyPage'
import NotFoundPage from './pages/NotFoundPage'
import PortfolioPage from './pages/PortfolioPage'
import ScannerPage from './pages/ScannerPage'
import SettingsPage from './pages/SettingsPage'
import StockDetailPage from './pages/StockDetailPage'
import WatchlistPage from './pages/WatchlistPage'

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
        <Route path="/watchlist" element={<WatchlistPage />} />
        <Route path="/scanner" element={<ScannerPage />} />
        <Route path="/stocks/:ticker" element={<StockDetailPage />} />
        <Route path="/methodology" element={<MethodologyPage />} />
        <Route path="/homework" element={<DailyHomeworkPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  )
}
