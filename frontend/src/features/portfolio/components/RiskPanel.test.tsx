import { screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import type { PositionOut, RiskResponse } from '../../../api/portfolio'
import { theme } from '../../../theme/theme'
import { server } from '../../../../tests/mocks/server'
import { renderWithProviders } from '../../../../tests/renderWithProviders'
import RiskPanel from './RiskPanel'

const aaplPosition: PositionOut = {
  id: 'pos_123',
  ticker: 'AAPL',
  quantity: 100,
  avg_cost_basis: 195.3,
  entry_date: '2026-05-14',
  current_price: 228.9,
  unrealized_pnl_pct: 17.2,
}

const msftPosition: PositionOut = {
  id: 'pos_456',
  ticker: 'MSFT',
  quantity: 10,
  avg_cost_basis: 300,
  entry_date: '2026-06-01',
  current_price: 410.5,
  unrealized_pnl_pct: 36.8,
}

function mockRisk(response: RiskResponse) {
  server.use(http.get('/api/portfolio/risk', () => HttpResponse.json(response)))
}

describe('RiskPanel', () => {
  it('renders total open risk with no breach banner and no flagged rows when nothing is breached', async () => {
    mockRisk({
      total_open_risk_pct: 3.2,
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

    renderWithProviders(<RiskPanel positions={[aaplPosition, msftPosition]} />)

    await waitFor(() =>
      expect(screen.getByRole('table', { name: 'Portfolio risk' })).toBeInTheDocument(),
    )
    expect(screen.getByText('Total Open Risk')).toBeInTheDocument()
    expect(screen.getByText('3.20%')).toBeInTheDocument()
    // No 6%-rule banner and no missing-risk-data note.
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    // No exit flags on either row.
    expect(screen.getAllByText('—')).toHaveLength(2)

    const aaplRow = screen.getByText('AAPL').closest('tr')
    expect(aaplRow).not.toHaveStyle({
      backgroundColor: theme.palette.riskBreach.background,
    })
  })

  it('visually flags the row and lists readable exit-flag labels when the 2% rule is breached on one position', async () => {
    mockRisk({
      total_open_risk_pct: 3.9,
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

    renderWithProviders(<RiskPanel positions={[aaplPosition, msftPosition]} />)

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

    // No portfolio-level 6%-rule banner for a per-position-only breach.
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('shows a prominent warning banner when the 6% rule is breached', async () => {
    mockRisk({
      total_open_risk_pct: 6.4,
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

    renderWithProviders(<RiskPanel positions={[aaplPosition]} />)

    const banner = await screen.findByRole('alert')
    expect(banner).toHaveTextContent('6% rule breached')
    expect(banner).toHaveTextContent('6.40%')
    expect(screen.getByText('6% rule contributor')).toBeInTheDocument()
  })

  it('surfaces a non-blocking note for a held position silently excluded from the risk response', async () => {
    mockRisk({
      total_open_risk_pct: 1.8,
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

    renderWithProviders(<RiskPanel positions={[aaplPosition, msftPosition]} />)

    const note = await screen.findByRole('status')
    expect(note).toHaveTextContent('MSFT')

    // MSFT never appears as a misleading zero-risk row in the risk table.
    const table = screen.getByRole('table', { name: 'Portfolio risk' })
    expect(table.textContent).not.toContain('MSFT')
  })

  it('falls back to a humanized label for an exit flag not in the known label map', async () => {
    mockRisk({
      total_open_risk_pct: 1.0,
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

    renderWithProviders(<RiskPanel positions={[aaplPosition]} />)

    expect(await screen.findByText('Some future flag')).toBeInTheDocument()
  })

  it('shows a loading state, then an ApiError via common/ErrorState on failure', async () => {
    server.use(
      http.get('/api/portfolio/risk', () =>
        HttpResponse.json({ detail: 'boom' }, { status: 500 }),
      ),
    )

    renderWithProviders(<RiskPanel positions={[aaplPosition]} />)

    expect(screen.getByText('Loading risk data...')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    expect(screen.getByText('Something went wrong')).toBeInTheDocument()
  })
})
