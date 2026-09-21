import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import type { PositionOut, RiskResponse } from '../../../api/portfolio'
import { theme } from '../../../theme/theme'
import { server } from '../../../../tests/mocks/server'
import { renderWithProviders } from '../../../../tests/renderWithProviders'
import RiskPanel, { type RiskPanelProps } from './RiskPanel'

function renderRiskPanel(positions: RiskPanelProps['positions']) {
  return renderWithProviders(
    <MemoryRouter>
      <RiskPanel positions={positions} />
    </MemoryRouter>,
  )
}

const aaplPosition: PositionOut = {
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
}

const msftPosition: PositionOut = {
  id: 'pos_456',
  ticker: 'MSFT',
  quantity: 10,
  avg_cost_basis: 300,
  entry_date: '2026-06-01',
  current_price: 410.5,
  unrealized_pnl_pct: 36.8,
  signal: 'HOLD',
  confidence: 45,
  confidence_band: 'Medium',
}

function mockRisk(response: RiskResponse) {
  server.use(http.get('/api/portfolio/risk', () => HttpResponse.json(response)))
}

describe('RiskPanel', () => {
  it('renders total open risk with no breach banner and no flagged rows when nothing is breached', async () => {
    mockRisk({
      total_open_risk_pct: 3.2,
      realized_losses_this_month_pct: 0,
      six_percent_rule_breached: false,
      positions: [
        {
          id: 'pos_123',
          ticker: 'AAPL',
          protective_stop: 210.15,
          position_risk_pct: 1.8,
          two_percent_rule_breached: false,
          exit_flags: [],
          // Non-null even though AAPL's own live signal below is BUY here --
          // proven distinctly non-BUY-gated by MSFT's HOLD row below still
          // also getting a real (different) target, not an em dash.
          profit_target: {
            price: 245.0,
            source: 'channel',
            distance_to_stop: 9.3,
            distance_to_target: 18.6,
            reward_risk_ratio: 2.0,
            meets_minimum_reward_risk: true,
          },
        },
        {
          id: 'pos_456',
          ticker: 'MSFT',
          protective_stop: 390.0,
          position_risk_pct: 1.4,
          two_percent_rule_breached: false,
          exit_flags: [],
          // MSFT's own live signal (below) is HOLD -- backend-profit-target-
          // open-position's whole point is that RiskPosition.profit_target
          // still shows here, unlike AnalysisResponse.profit_target would.
          profit_target: {
            price: 420.0,
            source: 'support_resistance',
            distance_to_stop: 12.0,
            distance_to_target: 9.5,
            reward_risk_ratio: 0.79,
            meets_minimum_reward_risk: false,
          },
        },
      ],
    })

    renderRiskPanel([aaplPosition, msftPosition])

    await waitFor(() =>
      expect(screen.getByRole('table', { name: 'Portfolio risk' })).toBeInTheDocument(),
    )
    expect(screen.getByText('Total Risk (Open + Realized)')).toBeInTheDocument()
    expect(screen.getByText('3.20%')).toBeInTheDocument()
    // No 6%-rule banner and no missing-risk-data note.
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.queryByRole('status')).not.toBeInTheDocument()

    // Both rows' Profit Target cells read straight off GET /api/portfolio
    // /risk's own `profit_target` field -- no per-row /analysis fetch, and
    // MSFT's still shows despite its HOLD signal. Both rows' (empty) Exit
    // Flags cells are the only remaining dashes.
    expect(screen.getByText('$245.00')).toBeInTheDocument()
    expect(screen.getByText('2.0:1')).toBeInTheDocument()
    expect(screen.getByText('$420.00')).toBeInTheDocument()
    expect(screen.getByText('0.8:1')).toBeInTheDocument()
    expect(screen.getAllByText('—')).toHaveLength(2)

    // Ticker cells link into stock detail (common/TickerLink).
    expect(screen.getByRole('link', { name: 'AAPL' })).toHaveAttribute(
      'href',
      '/stocks/AAPL',
    )
    expect(screen.getByRole('link', { name: 'MSFT' })).toHaveAttribute(
      'href',
      '/stocks/MSFT',
    )

    // Signal column cross-references the held-position list passed in via
    // `positions` (RiskPosition itself has no `signal` field) -- reusing
    // common/SignalBadge, same as WatchlistTable/PositionsTable.
    const aaplRow = screen.getByText('AAPL').closest('tr')
    expect(aaplRow).not.toHaveStyle({
      backgroundColor: theme.palette.riskBreach.background,
    })
    expect(within(aaplRow as HTMLElement).getByTestId('signal-badge')).toHaveTextContent(
      'BUY',
    )
    const msftRow = screen.getByText('MSFT').closest('tr')
    expect(within(msftRow as HTMLElement).getByTestId('signal-badge')).toHaveTextContent(
      'HOLD',
    )
  })

  it('renders an em dash in the Signal column for a held position whose signal could not be computed', async () => {
    mockRisk({
      total_open_risk_pct: 1.8,
      realized_losses_this_month_pct: 0,
      six_percent_rule_breached: false,
      positions: [
        {
          id: 'pos_123',
          ticker: 'AAPL',
          protective_stop: 210.15,
          position_risk_pct: 1.8,
          two_percent_rule_breached: false,
          exit_flags: [],
        },
      ],
    })

    const positionWithNullSignal: PositionOut = {
      ...aaplPosition,
      signal: null,
      confidence: null,
      confidence_band: null,
    }
    renderRiskPanel([positionWithNullSignal])

    await waitFor(() =>
      expect(screen.getByRole('table', { name: 'Portfolio risk' })).toBeInTheDocument(),
    )
    const aaplRow = screen.getByText('AAPL').closest('tr') as HTMLElement
    expect(within(aaplRow).queryByTestId('signal-badge')).not.toBeInTheDocument()
    // The (empty) Exit Flags cell, the null-signal Signal cell, and the
    // Profit Target cell (the mocked risk position above omits
    // `profit_target` entirely, matching the real backend's optional-field
    // "no candidate" case) all fall back to '—'.
    expect(within(aaplRow).getAllByText('—')).toHaveLength(3)
  })

  it('visually flags the row and lists readable exit-flag labels when the 2% rule is breached on one position', async () => {
    mockRisk({
      total_open_risk_pct: 3.9,
      realized_losses_this_month_pct: 0,
      six_percent_rule_breached: false,
      positions: [
        {
          id: 'pos_123',
          ticker: 'AAPL',
          protective_stop: 210.15,
          position_risk_pct: 2.5,
          two_percent_rule_breached: true,
          exit_flags: ['two_percent_rule_breached', 'stop_hit'],
        },
        {
          id: 'pos_456',
          ticker: 'MSFT',
          protective_stop: 390.0,
          position_risk_pct: 1.4,
          two_percent_rule_breached: false,
          exit_flags: [],
        },
      ],
    })

    renderRiskPanel([aaplPosition, msftPosition])

    await waitFor(() => expect(screen.getByText('AAPL')).toBeInTheDocument())

    // Human-readable labels, not raw snake_case.
    expect(screen.getByText('2% rule breached')).toBeInTheDocument()
    expect(screen.getByText('Stop hit')).toBeInTheDocument()
    expect(screen.queryByText('two_percent_rule_breached')).not.toBeInTheDocument()

    const aaplRow = screen.getByText('AAPL').closest('tr')
    const msftRow = screen.getByText('MSFT').closest('tr')
    expect(aaplRow).toHaveStyle({ backgroundColor: theme.palette.riskBreach.background })
    expect(msftRow).not.toHaveStyle({
      backgroundColor: theme.palette.riskBreach.background,
    })

    // The breaching row's own Position Risk number renders as a risk warning
    // (riskBreach.main), not success-green — a 5%/1.4% risk magnitude isn't
    // a "gain", and PR #66's review flagged the prior PercentChange reuse as
    // misleadingly green on a breaching row.
    const aaplRisk = screen.getByText('2.50%')
    expect(aaplRisk).toHaveStyle({ color: theme.palette.riskBreach.main })
    expect(aaplRisk).not.toHaveStyle({ color: theme.palette.success.main })
    const msftRisk = screen.getByText('1.40%')
    expect(msftRisk).toHaveStyle({ color: theme.palette.text.secondary })
    expect(msftRisk).not.toHaveStyle({ color: theme.palette.success.main })

    // No portfolio-level 6%-rule banner for a per-position-only breach.
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('shows a prominent warning banner when the 6% rule is breached', async () => {
    mockRisk({
      total_open_risk_pct: 6.4,
      realized_losses_this_month_pct: 0,
      six_percent_rule_breached: true,
      positions: [
        {
          id: 'pos_123',
          ticker: 'AAPL',
          protective_stop: 210.15,
          position_risk_pct: 5.0,
          two_percent_rule_breached: false,
          exit_flags: ['six_percent_rule_contributor'],
        },
      ],
    })

    renderRiskPanel([aaplPosition])

    const banner = await screen.findByRole('alert')
    expect(banner).toHaveTextContent('6% rule breached')
    expect(banner).toHaveTextContent('6.40%')
    expect(screen.getByText('6% rule contributor')).toBeInTheDocument()
  })

  it('surfaces a non-blocking note for a held position silently excluded from the risk response', async () => {
    mockRisk({
      total_open_risk_pct: 1.8,
      realized_losses_this_month_pct: 0,
      six_percent_rule_breached: false,
      positions: [
        {
          id: 'pos_123',
          ticker: 'AAPL',
          protective_stop: 210.15,
          position_risk_pct: 1.8,
          two_percent_rule_breached: false,
          exit_flags: [],
        },
        // MSFT is intentionally absent here, e.g. because its price/history
        // fetch failed (API.md's silent-exclusion rule) even though it's a
        // held position per `positions` below.
      ],
    })

    renderRiskPanel([aaplPosition, msftPosition])

    const note = await screen.findByRole('status')
    expect(note).toHaveTextContent('MSFT')
    // Singular pronoun agreement for exactly one missing ticker.
    expect(note).toHaveTextContent(
      "its price or history couldn't be fetched, so it's excluded",
    )

    // MSFT never appears as a misleading zero-risk row in the risk table.
    const table = screen.getByRole('table', { name: 'Portfolio risk' })
    expect(table.textContent).not.toContain('MSFT')
  })

  it('pluralizes the silent-exclusion note when more than one held position is missing', async () => {
    mockRisk({
      total_open_risk_pct: 0,
      realized_losses_this_month_pct: 0,
      six_percent_rule_breached: false,
      positions: [],
    })

    // Both AAPL and MSFT are held but absent from the risk response.
    renderRiskPanel([aaplPosition, msftPosition])

    const note = await screen.findByRole('status')
    expect(note).toHaveTextContent('AAPL, MSFT')
    expect(note).toHaveTextContent(
      "their price or history couldn't be fetched, so they're excluded",
    )
  })

  it('falls back to a humanized label for an exit flag not in the known label map', async () => {
    mockRisk({
      total_open_risk_pct: 1.0,
      realized_losses_this_month_pct: 0,
      six_percent_rule_breached: false,
      positions: [
        {
          id: 'pos_123',
          ticker: 'AAPL',
          protective_stop: 210.15,
          position_risk_pct: 1.0,
          two_percent_rule_breached: false,
          exit_flags: ['some_future_flag'],
        },
      ],
    })

    renderRiskPanel([aaplPosition])

    expect(await screen.findByText('Some future flag')).toBeInTheDocument()
  })

  it('shows a loading state, then an ApiError via common/ErrorState on failure', async () => {
    server.use(
      http.get('/api/portfolio/risk', () =>
        HttpResponse.json({ detail: 'boom' }, { status: 500 }),
      ),
    )

    renderRiskPanel([aaplPosition])

    expect(screen.getByText('Loading risk data...')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    expect(screen.getByText('Something went wrong')).toBeInTheDocument()
  })

  it('opens the Total Risk help popover with the open-vs-realized breakdown text (totalRiskHelp)', async () => {
    // Same PR #166 review-verified figures totalRiskHelp.test.ts hand-checks
    // directly -- this test locks in that the real value flows through
    // RiskPanel's own MetricHelp wiring, not just the helper in isolation
    // (docs/tasks/backend-trade-history-table-followups-followups.json).
    mockRisk({
      total_open_risk_pct: 693.72,
      realized_losses_this_month_pct: 691.79,
      six_percent_rule_breached: true,
      positions: [
        {
          id: 'pos_123',
          ticker: 'AAPL',
          protective_stop: 210.15,
          position_risk_pct: 1.93,
          two_percent_rule_breached: false,
          exit_flags: [],
        },
      ],
    })

    const user = userEvent.setup()
    renderRiskPanel([aaplPosition])

    await waitFor(() => expect(screen.getByText('693.72%')).toBeInTheDocument())

    await user.click(screen.getByRole('button', { name: 'Total Risk (Open + Realized) help' }))
    expect(
      screen.getByText(
        "1.93% from open positions + 691.79% from this month's realized losses = 693.72% total.",
      ),
    ).toBeInTheDocument()
  })
})
