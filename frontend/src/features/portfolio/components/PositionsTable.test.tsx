import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import type { PositionOut } from '../../../api/portfolio'
import { server } from '../../../../tests/mocks/server'
import { renderWithProviders } from '../../../../tests/renderWithProviders'
import PositionsTable from './PositionsTable'

const positions: PositionOut[] = [
  {
    id: 'pos_123',
    ticker: 'AAPL',
    quantity: 100,
    avg_cost_basis: 195.3,
    entry_date: '2026-05-14',
    current_price: 228.9,
    unrealized_pnl_pct: 17.2,
  },
  {
    id: 'pos_456',
    ticker: 'ZZZZ',
    quantity: 10,
    avg_cost_basis: 50,
    entry_date: '2026-06-01',
    current_price: null,
    unrealized_pnl_pct: null,
  },
]

describe('PositionsTable', () => {
  it('renders a row per position with formatted currency/percentage cells', () => {
    renderWithProviders(<PositionsTable positions={positions} />)

    const table = screen.getByRole('table')
    const rows = within(table).getAllByRole('row').slice(1)
    expect(rows).toHaveLength(2)

    expect(within(rows[0]).getByText('AAPL')).toBeInTheDocument()
    expect(within(rows[0]).getByText('$195.30')).toBeInTheDocument()
    expect(within(rows[0]).getByText('$228.90')).toBeInTheDocument()
    expect(within(rows[0]).getByText('+17.20%')).toBeInTheDocument()
  })

  it('renders an em dash for null current_price/unrealized_pnl_pct', () => {
    renderWithProviders(<PositionsTable positions={positions} />)

    const table = screen.getByRole('table')
    const rows = within(table).getAllByRole('row').slice(1)
    const zzzzRow = rows[1]

    expect(within(zzzzRow).getByText('ZZZZ')).toBeInTheDocument()
    const cells = within(zzzzRow).getAllByRole('cell')
    expect(cells.map((cell) => cell.textContent)).toContain('—')
  })

  it('renders the empty state when there are no positions', () => {
    renderWithProviders(<PositionsTable positions={[]} />)

    expect(
      screen.getByText('No positions yet. Add one to get started.'),
    ).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('opens a confirm dialog before deleting, and cancels without deleting', async () => {
    const user = userEvent.setup()
    renderWithProviders(<PositionsTable positions={positions} />)

    await user.click(screen.getByRole('button', { name: 'Delete AAPL' }))

    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByText(/delete aapl \(100 shares\)/i)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Cancel' }))

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('deletes the position on confirm', async () => {
    const user = userEvent.setup()
    renderWithProviders(<PositionsTable positions={positions} />)

    await user.click(screen.getByRole('button', { name: 'Delete AAPL' }))
    await user.click(screen.getByRole('button', { name: 'Delete' }))

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('surfaces a 404 ApiError via common/ErrorState when the position no longer exists', async () => {
    server.use(
      http.delete('/api/portfolio/positions/:id', () =>
        HttpResponse.json({ detail: 'Position not found' }, { status: 404 }),
      ),
    )
    const user = userEvent.setup()
    renderWithProviders(<PositionsTable positions={positions} />)

    await user.click(screen.getByRole('button', { name: 'Delete AAPL' }))
    await user.click(screen.getByRole('button', { name: 'Delete' }))

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    expect(screen.getByText('Not found')).toBeInTheDocument()
    expect(screen.getByText('Position not found')).toBeInTheDocument()
  })
})
