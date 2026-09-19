import { screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import type { PositionOut } from '../../../api/portfolio'
import { renderWithProviders } from '../../../../tests/renderWithProviders'
import PositionsGlanceTable from './PositionsGlanceTable'

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

const unpricedPosition: PositionOut = {
  id: 'pos_789',
  ticker: 'ZZZZ',
  quantity: 3,
  avg_cost_basis: 10,
  entry_date: '2026-01-01',
  current_price: null,
  unrealized_pnl_pct: null,
  signal: null,
  confidence: null,
  confidence_band: null,
}

const highPricedPosition: PositionOut = {
  id: 'pos_456',
  ticker: 'BRKA',
  quantity: 1,
  avg_cost_basis: 1000.5,
  entry_date: '2026-02-01',
  current_price: 1234.5,
  unrealized_pnl_pct: 23.4,
  signal: 'HOLD',
  confidence: 45,
  confidence_band: 'Medium',
}

function renderWithRouter(positions: PositionOut[]) {
  return renderWithProviders(
    <MemoryRouter>
      <PositionsGlanceTable positions={positions} />
    </MemoryRouter>,
  )
}

describe('PositionsGlanceTable', () => {
  it('renders a row per position with a ticker link into stock detail and its signal badge', () => {
    renderWithRouter([aaplPosition])

    expect(
      screen.getByRole('table', { name: 'Positions at a glance' }),
    ).toBeInTheDocument()
    const link = screen.getByRole('link', { name: 'AAPL' })
    expect(link).toHaveAttribute('href', '/stocks/AAPL')
    expect(screen.getByText('$228.90')).toBeInTheDocument()
    expect(screen.getByText('+17.20%')).toBeInTheDocument()
    expect(screen.getByTestId('signal-badge')).toHaveTextContent('BUY')
  })

  it('renders a 4-digit price with a thousands separator', () => {
    renderWithRouter([highPricedPosition])

    expect(screen.getByText('$1,234.50')).toBeInTheDocument()
  })

  it('renders an em dash for a position with no known price or signal', () => {
    renderWithRouter([unpricedPosition])

    const dashes = screen.getAllByText('—')
    expect(dashes).toHaveLength(3)
    expect(screen.queryByTestId('signal-badge')).not.toBeInTheDocument()
  })

  it('shows the empty state when there are no positions', () => {
    renderWithRouter([])

    expect(
      screen.getByText(
        'No positions yet. Add one from the Portfolio page to get started.',
      ),
    ).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })
})
