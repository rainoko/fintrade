import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { resetPortfolioStore } from '../../tests/mocks/handlers'
import { server } from '../../tests/mocks/server'
import { renderWithProviders } from '../../tests/renderWithProviders'
import PortfolioPage from './PortfolioPage'

describe('PortfolioPage', () => {
  beforeEach(() => {
    resetPortfolioStore()
  })

  afterEach(() => {
    resetPortfolioStore()
  })

  it('shows a loading state, then the equity stat cards and positions table', async () => {
    renderWithProviders(<PortfolioPage />)

    expect(screen.getByText('Loading portfolio...')).toBeInTheDocument()

    await waitFor(() =>
      expect(screen.getByRole('table', { name: 'Positions' })).toBeInTheDocument(),
    )

    expect(screen.getByText('Cash')).toBeInTheDocument()
    expect(screen.getByText('Positions Value')).toBeInTheDocument()
    expect(screen.getByText('Total Equity')).toBeInTheDocument()
    expect(screen.getByText('AAPL')).toBeInTheDocument()

    await waitFor(() =>
      expect(screen.getByRole('table', { name: 'Portfolio risk' })).toBeInTheDocument(),
    )
    expect(screen.getByText('Total Open Risk')).toBeInTheDocument()
  })

  it('shows the empty state when the portfolio has no positions', async () => {
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

    renderWithProviders(<PortfolioPage />)

    await waitFor(() =>
      expect(
        screen.getByText('No positions yet. Add one to get started.'),
      ).toBeInTheDocument(),
    )
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('surfaces a network-level ApiError via common/ErrorState', async () => {
    server.use(http.get('/api/portfolio', () => HttpResponse.error()))

    renderWithProviders(<PortfolioPage />)

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    expect(screen.getByText('Connection error')).toBeInTheDocument()
  })

  it('adds a new position end to end and reflects it in the refreshed table', async () => {
    const user = userEvent.setup()
    renderWithProviders(<PortfolioPage />)

    await waitFor(() =>
      expect(screen.getByRole('table', { name: 'Positions' })).toBeInTheDocument(),
    )

    await user.click(screen.getByRole('button', { name: 'Add Position' }))
    await user.type(screen.getByLabelText('Ticker'), 'MSFT')
    await user.type(screen.getByLabelText('Quantity'), '5')
    await user.type(screen.getByLabelText('Avg Cost Basis'), '400')
    await user.type(screen.getByLabelText('Entry Date'), '2026-02-01')
    await user.click(
      within(screen.getByRole('dialog')).getByRole('button', { name: 'Add Position' }),
    )

    await waitFor(() =>
      expect(screen.getByText('Added MSFT to your portfolio.')).toBeInTheDocument(),
    )
    await user.click(screen.getByRole('button', { name: 'Done' }))

    await waitFor(() => {
      const table = screen.getByRole('table', { name: 'Positions' })
      expect(within(table).getByText('MSFT')).toBeInTheDocument()
    })
  })

  it('deletes a position end to end and removes it from the refreshed table', async () => {
    const user = userEvent.setup()
    renderWithProviders(<PortfolioPage />)

    await waitFor(() => expect(screen.getByText('AAPL')).toBeInTheDocument())

    await user.click(screen.getByRole('button', { name: 'Delete AAPL' }))
    await user.click(screen.getByRole('button', { name: 'Delete' }))

    await waitFor(() =>
      expect(
        screen.getByText('No positions yet. Add one to get started.'),
      ).toBeInTheDocument(),
    )
  })
})
