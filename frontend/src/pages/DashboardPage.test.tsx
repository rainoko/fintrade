import { screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { resetPortfolioStore } from '../../tests/mocks/handlers'
import { server } from '../../tests/mocks/server'
import { renderWithProviders } from '../../tests/renderWithProviders'
import DashboardPage from './DashboardPage'

function renderDashboard() {
  return renderWithProviders(
    <MemoryRouter>
      <DashboardPage />
    </MemoryRouter>,
  )
}

describe('DashboardPage', () => {
  beforeEach(() => {
    resetPortfolioStore()
  })

  afterEach(() => {
    resetPortfolioStore()
  })

  it('shows a loading state, then the equity summary, risk summary, and positions-at-a-glance table', async () => {
    renderDashboard()

    expect(screen.getByText('Loading dashboard...')).toBeInTheDocument()

    await waitFor(() =>
      expect(
        screen.getByRole('table', { name: 'Positions at a glance' }),
      ).toBeInTheDocument(),
    )

    expect(screen.getByText('Cash')).toBeInTheDocument()
    expect(screen.getByText('Positions Value')).toBeInTheDocument()
    expect(screen.getByText('Total Equity')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'AAPL' })).toHaveAttribute(
      'href',
      '/stocks/AAPL',
    )

    await waitFor(() => expect(screen.getByText('Total Open Risk')).toBeInTheDocument())
    expect(screen.getByText('Positions Breaching 2% Rule')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()

    // Ticker lookup entry point is present alongside the summary.
    expect(screen.getByLabelText('Look up a ticker')).toBeInTheDocument()
  })

  it('shows the first-run empty state when the portfolio has no positions yet', async () => {
    server.use(
      http.get('/api/portfolio', () =>
        HttpResponse.json({
          equity: { cash: 5000, positions_value: 0, total: 5000 },
          positions: [],
        }),
      ),
      http.get('/api/portfolio/risk', () =>
        HttpResponse.json({
          total_open_risk_pct: 0,
          six_percent_rule_breached: false,
          positions: [],
        }),
      ),
    )

    renderDashboard()

    await waitFor(() =>
      expect(
        screen.getByText('No positions yet. Add one from the Portfolio page to get started.'),
      ).toBeInTheDocument(),
    )
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    await waitFor(() => expect(screen.getByText('0.00%')).toBeInTheDocument())
    expect(screen.getByText('Positions Breaching 2% Rule')).toBeInTheDocument()
  })

  it('shows the 6% risk breach warning summary when the rule is breached', async () => {
    server.use(
      http.get('/api/portfolio/risk', () =>
        HttpResponse.json({
          total_open_risk_pct: 6.8,
          six_percent_rule_breached: true,
          positions: [
            {
              id: 'pos_123',
              ticker: 'AAPL',
              protective_stop: 210.15,
              position_risk_pct: 6.8,
              two_percent_rule_breached: true,
              exit_flags: ['two_percent_rule_breached', 'six_percent_rule_contributor'],
            },
          ],
        }),
      ),
    )

    renderDashboard()

    const banner = await screen.findByRole('alert')
    expect(banner).toHaveTextContent('6% rule breached')
    expect(banner).toHaveTextContent('6.80%')

    await waitFor(() => expect(screen.getByText('1')).toBeInTheDocument())
    expect(screen.getByText('Positions Breaching 2% Rule')).toBeInTheDocument()
  })

  it('surfaces a network-level ApiError via common/ErrorState', async () => {
    server.use(http.get('/api/portfolio', () => HttpResponse.error()))

    renderDashboard()

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    expect(screen.getByText('Connection error')).toBeInTheDocument()
  })
})
