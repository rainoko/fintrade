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

    await waitFor(() =>
      expect(screen.getByText('Total Risk (Open + Realized)')).toBeInTheDocument(),
    )
    expect(screen.getByText('Positions Breaching 2% Rule')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()

    // No positions flagged in the default fixture.
    expect(
      screen.getByText('No positions currently flagged to sell.'),
    ).toBeInTheDocument()

    // Ticker lookup entry point is present alongside the summary.
    expect(screen.getByLabelText('Look up a ticker')).toBeInTheDocument()
  })

  it('shows the first-run empty state when the portfolio has no positions yet', async () => {
    server.use(
      http.get('/api/portfolio', () =>
        HttpResponse.json({
          trading_mode: { mode: 'swing', day_trader_timeframe_triple: null },
          equity: { cash: 5000, positions_value: 0, total: 5000 },
          positions: [],
        }),
      ),
      http.get('/api/portfolio/risk', () =>
        HttpResponse.json({
          trading_mode: { mode: 'swing', day_trader_timeframe_triple: null },
          total_open_risk_pct: 0,
          realized_losses_this_month_pct: 0,
          six_percent_rule_breached: false,
          positions: [],
        }),
      ),
    )

    renderDashboard()

    await waitFor(() =>
      expect(
        screen.getByText(
          'No positions yet. Add one from the Portfolio page to get started.',
        ),
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
          trading_mode: { mode: 'swing', day_trader_timeframe_triple: null },
          total_open_risk_pct: 6.8,
          realized_losses_this_month_pct: 0,
          six_percent_rule_breached: true,
          positions: [
            {
              id: 'pos_123',
              ticker: 'AAPL',
              protective_stop: 210.15,
              trailing_stop: 210.15,
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

    // The breaching position also shows up in the sell-flagged list, with
    // human-readable flag labels.
    const sellFlaggedTable = await screen.findByRole('table', {
      name: 'Positions flagged to sell',
    })
    expect(sellFlaggedTable).toHaveTextContent('AAPL')
    expect(screen.getByText('2% rule breached')).toBeInTheDocument()
    expect(screen.getByText('6% rule contributor')).toBeInTheDocument()
  })

  it('surfaces a network-level ApiError via common/ErrorState', async () => {
    server.use(http.get('/api/portfolio', () => HttpResponse.error()))

    renderDashboard()

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    expect(screen.getByText('Connection error')).toBeInTheDocument()
  })

  it('shows exactly one alert (not two stacked) when GET /api/portfolio/risk fails, with RiskSummaryCard and SellFlaggedPositionsCard both mounted', async () => {
    // RiskSummaryCard and SellFlaggedPositionsCard both call
    // usePortfolioRisk() and, before this fix, both independently rendered a
    // full common/ErrorState for the same failure -- the exact
    // sibling-duplication shape pr-reviewer found blocking on PortfolioPage's
    // PositionsTable/RiskPanel (PR #258). This regression test asserts the
    // page-level composition specifically, since each card's own standalone
    // test can't catch a duplicate that only appears once both are mounted
    // together, same lesson PortfolioPage.test.tsx's equivalent regression
    // test (PR #258) already applied there.
    server.use(
      http.get('/api/portfolio/risk', () =>
        HttpResponse.json({ detail: 'boom' }, { status: 500 }),
      ),
    )

    renderDashboard()

    const alerts = await screen.findAllByRole('alert')
    expect(alerts).toHaveLength(1)
    expect(alerts[0]).toHaveTextContent('Something went wrong')
    // SellFlaggedPositionsCard renders nothing (not a second alert, not its
    // own loading/empty state) for this failure.
    expect(screen.queryByText('Positions Flagged to Sell')).not.toBeInTheDocument()
    expect(
      screen.queryByText('No positions currently flagged to sell.'),
    ).not.toBeInTheDocument()
  })
})
