import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it } from 'vitest'
import type { IBKRScannerResultOut } from '../../../api/ibkr'
import { resetWatchlistStore } from '../../../../tests/mocks/handlers'
import { server } from '../../../../tests/mocks/server'
import { renderWithProviders } from '../../../../tests/renderWithProviders'
import ScannerResultsTable from './ScannerResultsTable'

function renderResultsTable(results: IBKRScannerResultOut[]) {
  return renderWithProviders(
    <MemoryRouter>
      <ScannerResultsTable results={results} />
    </MemoryRouter>,
  )
}

const results: IBKRScannerResultOut[] = [
  { conid: 1001, symbol: 'AAPL', company_name: 'Apple Inc.', rank: 1 },
  { conid: 1002, symbol: 'MSFT', company_name: 'Microsoft Corp.', rank: 2 },
]

describe('ScannerResultsTable', () => {
  beforeEach(() => {
    resetWatchlistStore()
  })

  it('renders every result with a TickerLink and company/rank columns', () => {
    renderResultsTable(results)

    expect(screen.getByRole('link', { name: 'AAPL' })).toHaveAttribute(
      'href',
      '/stocks/AAPL',
    )
    expect(screen.getByText('Apple Inc.')).toBeInTheDocument()
    expect(screen.getByText('Microsoft Corp.')).toBeInTheDocument()
  })

  it('renders a conid fallback (no link, no add action) for a result with no symbol', () => {
    renderResultsTable([{ conid: 2001, symbol: null, company_name: null, rank: null }])

    expect(screen.getByText('#2001')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Add to watchlist/ })).not.toBeInTheDocument()
  })

  it('shows the empty state (distinct from the unavailable state) for a zero-match scan', () => {
    renderResultsTable([])

    expect(screen.getByText('No matches for this scan.')).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('adds a result to the watchlist and flips the button to Added', async () => {
    const user = userEvent.setup()
    renderResultsTable(results)

    const addButtons = screen.getAllByRole('button', { name: 'Add to watchlist' })
    await user.click(addButtons[0])

    await waitFor(() =>
      expect(screen.getAllByRole('button', { name: 'Added' })).toHaveLength(1),
    )
    expect(screen.getAllByRole('button', { name: 'Add to watchlist' })).toHaveLength(1)
  })

  it('surfaces an add-to-watchlist failure via common/ErrorState', async () => {
    server.use(
      http.post('/api/watchlist', () =>
        HttpResponse.json({ detail: 'Something went wrong.' }, { status: 422 }),
      ),
    )
    const user = userEvent.setup()
    renderResultsTable(results)

    await user.click(screen.getAllByRole('button', { name: 'Add to watchlist' })[0])

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    expect(screen.getByText('Something went wrong.')).toBeInTheDocument()
  })
})
