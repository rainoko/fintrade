import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import type { WatchlistItemOut } from '../api/watchlist'
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

  it('renders the Personal Breadth widget above the table, aggregating the watchlist + portfolio union', async () => {
    renderWatchlistPage()

    await waitFor(() =>
      expect(screen.getByRole('table', { name: 'Watchlist' })).toBeInTheDocument(),
    )

    // Seeded mocks: watchlist {AAPL, MSFT}, portfolio {AAPL} -> union {AAPL, MSFT},
    // with AAPL BULLISH and MSFT NEUTRAL (tests/mocks/handlers.ts's
    // mockTickerTideTrends), independent of resetPortfolioStore not being
    // called here.
    expect(
      screen.getByText('Personal Breadth (Watchlist + Portfolio)'),
    ).toBeInTheDocument()
    expect(screen.getAllByText('1 (50.0%)')).toHaveLength(2)
    expect(screen.getByText('0 (0.0%)')).toBeInTheDocument()
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

  it('shows an animated skeleton row for a newly added ticker while the recompute refetch is still in flight, then the real row', async () => {
    // Delays the GET refetch triggered by the POST's invalidation -- the
    // initial page-load GET (already resolved via the waitFor below) is
    // unaffected, since server.use only swaps the handler for *subsequent*
    // requests. This is the deliberately-slow response this task's checklist
    // calls for, actually exercising the in-between skeleton state rather
    // than a fast POST+refetch settling before any assertion could observe it.
    let resolveGet: () => void = () => {}
    const user = userEvent.setup()
    renderWatchlistPage()

    await waitFor(() =>
      expect(screen.getByRole('table', { name: 'Watchlist' })).toBeInTheDocument(),
    )

    server.use(
      http.get('/api/watchlist', async () => {
        await new Promise<void>((resolve) => {
          resolveGet = resolve
        })
        const items: WatchlistItemOut[] = [
          {
            ticker: 'AAPL',
            added_at: '2026-09-10T09:15:00Z',
            signal: null,
            confidence: null,
            confidence_band: null,
          },
          {
            ticker: 'MSFT',
            added_at: '2026-09-12T09:15:00Z',
            signal: null,
            confidence: null,
            confidence_band: null,
          },
          {
            ticker: 'TSLA',
            added_at: '2026-09-19T00:00:00Z',
            signal: 'SELL',
            confidence: 30,
            confidence_band: 'Low',
          },
        ]
        return HttpResponse.json({ items })
      }),
    )

    await user.type(screen.getByLabelText('Add ticker to watchlist'), 'TSLA')
    await user.click(screen.getByRole('button', { name: 'Add' }))

    // POST has resolved (fast) and the refetch it triggered is now in
    // flight (deliberately held open above) -- the skeleton row is the only
    // visual indication a TSLA row is coming at all.
    await waitFor(() =>
      expect(screen.getAllByTestId('watchlist-skeleton').length).toBeGreaterThan(0),
    )
    const table = screen.getByRole('table', { name: 'Watchlist' })
    expect(within(table).queryByText('TSLA')).not.toBeInTheDocument()
    // The Add button itself stays disabled/loading for this same window.
    expect(screen.getByRole('button', { name: 'Add' })).toBeDisabled()

    resolveGet()

    await waitFor(() => expect(within(table).getByText('TSLA')).toBeInTheDocument())
    expect(screen.queryByTestId('watchlist-skeleton')).not.toBeInTheDocument()
  })

  it('clears the skeleton and surfaces the error when the add POST fails, leaving no orphaned skeleton row', async () => {
    server.use(
      http.post('/api/watchlist', () =>
        HttpResponse.json({ detail: 'Something went wrong.' }, { status: 422 }),
      ),
    )
    const user = userEvent.setup()
    renderWatchlistPage()

    await waitFor(() =>
      expect(screen.getByRole('table', { name: 'Watchlist' })).toBeInTheDocument(),
    )

    await user.type(screen.getByLabelText('Add ticker to watchlist'), 'TSLA')
    await user.click(screen.getByRole('button', { name: 'Add' }))

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    expect(screen.getByText('Something went wrong.')).toBeInTheDocument()
    expect(screen.queryByTestId('watchlist-skeleton')).not.toBeInTheDocument()
    const table = screen.getByRole('table', { name: 'Watchlist' })
    expect(within(table).queryByText('TSLA')).not.toBeInTheDocument()
  })

  it('does not leave a stray skeleton row when re-adding an already-watched ticker (idempotent no-op)', async () => {
    const user = userEvent.setup()
    renderWatchlistPage()

    await waitFor(() => expect(screen.getByText('AAPL')).toBeInTheDocument())

    await user.type(screen.getByLabelText('Add ticker to watchlist'), 'AAPL')
    await user.click(screen.getByRole('button', { name: 'Add' }))

    // The field clears once the (no-op) add settles -- the only externally
    // observable signal here, since a no-op add never shows a skeleton or
    // changes the table at all.
    await waitFor(() =>
      expect(screen.getByLabelText('Add ticker to watchlist')).toHaveValue(''),
    )
    expect(screen.queryByTestId('watchlist-skeleton')).not.toBeInTheDocument()
    const table = screen.getByRole('table', { name: 'Watchlist' })
    expect(within(table).getAllByText('AAPL')).toHaveLength(1)
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
