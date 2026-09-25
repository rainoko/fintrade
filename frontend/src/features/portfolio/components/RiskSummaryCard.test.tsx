import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import type { RiskResponse } from '../../../api/portfolio'
import { server } from '../../../../tests/mocks/server'
import { renderWithProviders } from '../../../../tests/renderWithProviders'
import RiskSummaryCard from './RiskSummaryCard'

function mockRisk(response: RiskResponse) {
  server.use(http.get('/api/portfolio/risk', () => HttpResponse.json(response)))
}

describe('RiskSummaryCard', () => {
  it('shows a loading state, then total risk and a zero breach count when nothing is breached', async () => {
    mockRisk({
      trading_mode: { mode: 'swing', day_trader_timeframe_triple: null },
      total_open_risk_pct: 3.2,
      realized_losses_this_month_pct: 0,
      six_percent_rule_breached: false,
      positions: [
        {
          id: 'pos_123',
          ticker: 'AAPL',
          protective_stop: 210.15,
          trailing_stop: 210.15,
          position_risk_pct: 1.8,
          two_percent_rule_breached: false,
          exit_flags: [],
        },
      ],
    })

    renderWithProviders(<RiskSummaryCard />)

    expect(screen.getByText('Loading risk summary...')).toBeInTheDocument()

    await waitFor(() => expect(screen.getByText('3.20%')).toBeInTheDocument())
    expect(screen.getByText('Total Risk (Open + Realized)')).toBeInTheDocument()
    expect(screen.getByText('Positions Breaching 2% Rule')).toBeInTheDocument()
    expect(screen.getByText('0')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('counts positions breaching the 2% rule and shows the 6% breach banner', async () => {
    mockRisk({
      trading_mode: { mode: 'swing', day_trader_timeframe_triple: null },
      total_open_risk_pct: 6.4,
      realized_losses_this_month_pct: 0,
      six_percent_rule_breached: true,
      positions: [
        {
          id: 'pos_123',
          ticker: 'AAPL',
          protective_stop: 210.15,
          trailing_stop: 210.15,
          position_risk_pct: 3.2,
          two_percent_rule_breached: true,
          exit_flags: ['two_percent_rule_breached'],
        },
        {
          id: 'pos_456',
          ticker: 'MSFT',
          protective_stop: 390.0,
          trailing_stop: 390.0,
          position_risk_pct: 3.2,
          two_percent_rule_breached: true,
          exit_flags: ['two_percent_rule_breached'],
        },
      ],
    })

    renderWithProviders(<RiskSummaryCard />)

    const banner = await screen.findByRole('alert')
    expect(banner).toHaveTextContent('6% rule breached')
    expect(banner).toHaveTextContent('6.40%')
    expect(screen.getByText('2')).toBeInTheDocument()
  })

  it('shows an ApiError via common/ErrorState on failure', async () => {
    server.use(
      http.get('/api/portfolio/risk', () =>
        HttpResponse.json({ detail: 'boom' }, { status: 500 }),
      ),
    )

    renderWithProviders(<RiskSummaryCard />)

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    expect(screen.getByText('Something went wrong')).toBeInTheDocument()
  })

  it('opens the Total Risk help popover with the open-vs-realized breakdown text (totalRiskHelp)', async () => {
    // Same PR #166 review-verified figures totalRiskHelp.test.ts hand-checks
    // directly -- this test locks in that the real value flows through
    // RiskSummaryCard's own MetricHelp wiring, not just the helper in
    // isolation (docs/tasks/backend-trade-history-table-followups-
    // followups.json).
    mockRisk({
      trading_mode: { mode: 'swing', day_trader_timeframe_triple: null },
      total_open_risk_pct: 693.72,
      realized_losses_this_month_pct: 691.79,
      six_percent_rule_breached: true,
      positions: [
        {
          id: 'pos_123',
          ticker: 'AAPL',
          protective_stop: 210.15,
          trailing_stop: 210.15,
          position_risk_pct: 1.93,
          two_percent_rule_breached: false,
          exit_flags: [],
        },
      ],
    })

    const user = userEvent.setup()
    renderWithProviders(<RiskSummaryCard />)

    await waitFor(() => expect(screen.getByText('693.72%')).toBeInTheDocument())

    await user.click(
      screen.getByRole('button', { name: 'Total Risk (Open + Realized) help' }),
    )
    expect(
      screen.getByText(
        "1.93% from open positions + 691.79% from this month's realized losses = 693.72% total.",
      ),
    ).toBeInTheDocument()
  })
})
