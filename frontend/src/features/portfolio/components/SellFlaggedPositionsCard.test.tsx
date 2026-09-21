import { screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import type { RiskResponse } from '../../../api/portfolio'
import { server } from '../../../../tests/mocks/server'
import { renderWithProviders } from '../../../../tests/renderWithProviders'
import SellFlaggedPositionsCard from './SellFlaggedPositionsCard'

function renderCard() {
  return renderWithProviders(
    <MemoryRouter>
      <SellFlaggedPositionsCard />
    </MemoryRouter>,
  )
}

function mockRisk(response: RiskResponse) {
  server.use(http.get('/api/portfolio/risk', () => HttpResponse.json(response)))
}

describe('SellFlaggedPositionsCard', () => {
  it('shows a loading state, then an empty-state message when no positions are flagged', async () => {
    mockRisk({
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
        },
      ],
    })

    renderCard()

    expect(screen.getByText('Loading sell-flagged positions...')).toBeInTheDocument()

    await waitFor(() =>
      expect(
        screen.getByText('No positions currently flagged to sell.'),
      ).toBeInTheDocument(),
    )
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('lists only the positions with a non-empty exit_flags, with human-readable flag labels', async () => {
    mockRisk({
      total_open_risk_pct: 4.5,
      realized_losses_this_month_pct: 0,
      six_percent_rule_breached: false,
      positions: [
        {
          id: 'pos_123',
          ticker: 'AAPL',
          protective_stop: 210.15,
          trailing_stop: 210.15,
          position_risk_pct: 2.5,
          two_percent_rule_breached: true,
          exit_flags: ['two_percent_rule_breached', 'stop_hit'],
        },
        {
          id: 'pos_456',
          ticker: 'MSFT',
          protective_stop: 390.0,
          trailing_stop: 390.0,
          position_risk_pct: 1.4,
          two_percent_rule_breached: false,
          exit_flags: [],
        },
      ],
    })

    renderCard()

    const table = await screen.findByRole('table', { name: 'Positions flagged to sell' })
    expect(table).toHaveTextContent('AAPL')
    expect(table).not.toHaveTextContent('MSFT')

    expect(screen.getByText('2% rule breached')).toBeInTheDocument()
    expect(screen.getByText('Stop hit')).toBeInTheDocument()
    expect(screen.queryByText('two_percent_rule_breached')).not.toBeInTheDocument()

    // Ticker cell links into the stock detail page (common/TickerLink).
    expect(screen.getByRole('link', { name: 'AAPL' })).toHaveAttribute(
      'href',
      '/stocks/AAPL',
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
          trailing_stop: 210.15,
          position_risk_pct: 1.0,
          two_percent_rule_breached: false,
          exit_flags: ['some_future_flag'],
        },
      ],
    })

    renderCard()

    expect(await screen.findByText('Some future flag')).toBeInTheDocument()
  })

  it('shows an ApiError via common/ErrorState on failure', async () => {
    server.use(
      http.get('/api/portfolio/risk', () =>
        HttpResponse.json({ detail: 'boom' }, { status: 500 }),
      ),
    )

    renderCard()

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    expect(screen.getByText('Something went wrong')).toBeInTheDocument()
  })
})
