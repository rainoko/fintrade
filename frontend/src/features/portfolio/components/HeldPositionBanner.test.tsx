import { screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import type { PortfolioResponse, RiskResponse } from '../../../api/portfolio'
import { server } from '../../../../tests/mocks/server'
import {
  createTestQueryClient,
  renderWithProviders,
} from '../../../../tests/renderWithProviders'
import { portfolioKeys } from '../hooks/queryKeys'
import HeldPositionBanner from './HeldPositionBanner'

function mockPortfolio(response: PortfolioResponse) {
  server.use(http.get('/api/portfolio', () => HttpResponse.json(response)))
}

function mockRisk(response: RiskResponse) {
  server.use(http.get('/api/portfolio/risk', () => HttpResponse.json(response)))
}

const aaplPortfolio: PortfolioResponse = {
  trading_mode: { mode: 'swing', day_trader_timeframe_triple: null },
  equity: { cash: 5000, positions_value: 22890, total: 27890 },
  positions: [
    {
      id: 'pos_123',
      ticker: 'AAPL',
      quantity: 100,
      avg_cost_basis: 195.3,
      entry_date: '2026-05-14',
      current_price: 228.9,
      unrealized_pnl_pct: 17.2,
      signal: 'BUY',
      confidence: 72,
      confidence_band: 'High',
    },
  ],
}

describe('HeldPositionBanner', () => {
  it('shows entry price/quantity/date, protective stop, and profit target for a held position', async () => {
    mockPortfolio(aaplPortfolio)
    mockRisk({
      trading_mode: { mode: 'swing', day_trader_timeframe_triple: null },
      total_open_risk_pct: 1.8,
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
          profit_target: {
            price: 245.0,
            source: 'channel',
            distance_to_stop: 9.3,
            distance_to_target: 18.6,
            reward_risk_ratio: 2.0,
            meets_minimum_reward_risk: true,
          },
        },
      ],
    })

    renderWithProviders(<HeldPositionBanner ticker="AAPL" />)

    const banner = await screen.findByRole('note', { name: 'You hold this position' })
    expect(within(banner).getByText('$195.30 · 100 sh · 2026-05-14')).toBeInTheDocument()
    expect(within(banner).getByText('$210.15')).toBeInTheDocument()
    expect(within(banner).getByText('$245.00')).toBeInTheDocument()
    expect(within(banner).getByText('2.0:1')).toBeInTheDocument()
  })

  it("renders nothing for a ticker that isn't a held position", async () => {
    mockPortfolio(aaplPortfolio)
    mockRisk({
      trading_mode: { mode: 'swing', day_trader_timeframe_triple: null },
      total_open_risk_pct: 1.8,
      realized_losses_this_month_pct: 0,
      six_percent_rule_breached: false,
      positions: [],
    })
    const queryClient = createTestQueryClient()

    renderWithProviders(<HeldPositionBanner ticker="ZZZZ" />, { queryClient })

    // Wait for the portfolio fetch to actually resolve (not just "still
    // loading") before asserting the banner's absence, so this proves the
    // no-match case specifically rather than a race that would pass either way.
    await waitFor(() =>
      expect(queryClient.getQueryState(portfolioKeys.all)?.status).toBe('success'),
    )
    expect(screen.queryByRole('note')).not.toBeInTheDocument()
  })

  it('shows field-specific warning icons (not an em dash) on Current Stop and Profit Target when GET /api/portfolio/risk fails', async () => {
    mockPortfolio(aaplPortfolio)
    server.use(
      http.get('/api/portfolio/risk', () =>
        HttpResponse.json(
          { detail: 'Market data provider unavailable' },
          { status: 503 },
        ),
      ),
    )

    renderWithProviders(<HeldPositionBanner ticker="AAPL" />)

    const banner = await screen.findByRole('note', { name: 'You hold this position' })
    // Still shows the (portfolio-sourced, unaffected by the risk failure)
    // entry price line.
    expect(within(banner).getByText('$195.30 · 100 sh · 2026-05-14')).toBeInTheDocument()

    // Field-specific aria-labels (not a shared "Risk data unavailable") so a
    // screen reader user can tell which field failed from the label alone.
    expect(
      await within(banner).findByLabelText('Current Stop unavailable'),
    ).toBeInTheDocument()
    expect(within(banner).getByLabelText('Profit target unavailable')).toBeInTheDocument()
    // No misleading '—' ("no stop/target configured") anywhere in the banner
    // for this genuine fetch-failure case.
    expect(within(banner).queryByText('—')).not.toBeInTheDocument()
  })

  it('falls back to an em dash for stop/target when the ticker is held but absent from the risk response', async () => {
    mockPortfolio(aaplPortfolio)
    mockRisk({
      trading_mode: { mode: 'swing', day_trader_timeframe_triple: null },
      total_open_risk_pct: 0,
      realized_losses_this_month_pct: 0,
      six_percent_rule_breached: false,
      positions: [],
    })

    renderWithProviders(<HeldPositionBanner ticker="AAPL" />)

    const banner = await screen.findByRole('note', { name: 'You hold this position' })
    expect(within(banner).getByText('$195.30 · 100 sh · 2026-05-14')).toBeInTheDocument()
    expect(within(banner).getAllByText('—').length).toBeGreaterThan(0)
  })
})
