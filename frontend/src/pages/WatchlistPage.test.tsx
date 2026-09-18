import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { resetWatchlistStore } from '../../tests/mocks/handlers'
import { server } from '../../tests/mocks/server'
import { renderWithProviders } from '../../tests/renderWithProviders'
import WatchlistPage from './WatchlistPage'

function renderWatchlistPage() {
  return renderWithProviders(
    <MemoryRouter>
      <WatchlistPage />
    </MemoryRouter>,
  )
}

describe('WatchlistPage', () => {
  beforeEach(() => {
    resetWatchlistStore()
  })

  afterEach(() => {
    resetWatchlistStore()
  })

  it('shows a loading state, then the watchlist table with the seeded tickers', async () => {
    renderWatchlistPage()

    expect(screen.getByText('Loading watchlist...')).toBeInTheDocument()

    await waitFor(() =>
      expect(screen.getByRole('table', { name: 'Watchlist' })).toBeInTheDocument(),
    )

    expect(screen.getByText('AAPL')).toBeInTheDocument()
    expect(screen.getByText('MSFT')).toBeInTheDocument()
  })

  it('shows the empty state when the watchlist has no tickers', async () => {
    server.use(http.get('/api/watchlist', () => HttpResponse.json({ items: [] })))

    renderWatchlistPage()

    await waitFor(() =>
      expect(
        screen.getByText('Your watchlist is empty. Add a ticker to get started.'),
      ).toBeInTheDocument(),
    )
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('surfaces a network-level ApiError via common/ErrorState', async () => {
    server.use(http.get('/api/watchlist', () => HttpResponse.error()))

    renderWatchlistPage()

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    expect(screen.getByText('Connection error')).toBeInTheDocument()
  })

  it('adds a new ticker end to end and reflects it in the refreshed table', async () => {
    const user = userEvent.setup()
    renderWatchlistPage()

    await waitFor(() =>
      expect(screen.getByRole('table', { name: 'Watchlist' })).toBeInTheDocument(),
    )

    await user.type(screen.getByLabelText('Add ticker to watchlist'), 'TSLA')
    await user.click(screen.getByRole('button', { name: 'Add' }))

    await waitFor(() => {
      const table = screen.getByRole('table', { name: 'Watchlist' })
      expect(within(table).getByText('TSLA')).toBeInTheDocument()
    })
  })

  it('removes a ticker end to end and drops it from the refreshed table', async () => {
    const user = userEvent.setup()
    renderWatchlistPage()

    await waitFor(() => expect(screen.getByText('AAPL')).toBeInTheDocument())

    await user.click(screen.getByRole('button', { name: 'Remove AAPL' }))
    await user.click(screen.getByRole('button', { name: 'Remove' }))

    await waitFor(() => expect(screen.queryByText('AAPL')).not.toBeInTheDocument())
    expect(screen.getByText('MSFT')).toBeInTheDocument()
  })
})
