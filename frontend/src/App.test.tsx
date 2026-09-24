import { screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { renderWithProviders } from '../tests/renderWithProviders'
import App from './App'

// Route-table smoke test: confirms every route in App.tsx resolves to its
// page inside the shared AppShell layout, and that an unmatched path falls
// through to the 404 page. StockDetailPage's heading is the ticker itself
// (see StockDetailPage.tsx/frontend-stock-analysis-page), not a static
// "Stock Detail" placeholder. Real page content/behavior is covered by each
// page's own tests (DashboardPage.test.tsx, PortfolioPage.test.tsx,
// StockDetailPage.test.tsx).
describe('App', () => {
  it.each([
    ['/', 'Dashboard'],
    ['/portfolio', 'Portfolio'],
    ['/watchlist', 'Watchlist'],
    ['/stocks/AAPL', 'AAPL'],
    ['/methodology', 'Signals We Considered'],
    ['/homework', 'Daily Homework'],
  ])('renders the page mapped to %s', (path, heading) => {
    renderWithProviders(
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>,
    )

    expect(screen.getByRole('heading', { name: heading })).toBeInTheDocument()
  })

  it('renders the 404 page for an unmatched route', () => {
    renderWithProviders(
      <MemoryRouter initialEntries={['/does-not-exist']}>
        <App />
      </MemoryRouter>,
    )

    expect(screen.getByRole('heading', { name: /page not found/i })).toBeInTheDocument()
  })

  it('renders the nav shell around every route', () => {
    renderWithProviders(
      <MemoryRouter initialEntries={['/']}>
        <App />
      </MemoryRouter>,
    )

    expect(screen.getByRole('link', { name: /dashboard/i })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /portfolio/i })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /watchlist/i })).toBeInTheDocument()
  })
})
