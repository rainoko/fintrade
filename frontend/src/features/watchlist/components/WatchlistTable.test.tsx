import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import type { WatchlistItemOut } from '../../../api/watchlist'
import { server } from '../../../../tests/mocks/server'
import { renderWithProviders } from '../../../../tests/renderWithProviders'
import WatchlistTable, { type WatchlistTableProps } from './WatchlistTable'

function renderWatchlistTable(items: WatchlistTableProps['items']) {
  return renderWithProviders(
    <MemoryRouter>
      <WatchlistTable items={items} />
    </MemoryRouter>,
  )
}

const items: WatchlistItemOut[] = [
  {
    ticker: 'AAPL',
    added_at: '2026-09-10T09:15:00Z',
    signal: 'BUY',
    confidence: 72,
    confidence_band: 'High',
  },
  {
    ticker: 'MSFT',
    added_at: '2026-09-12T09:15:00Z',
    signal: 'HOLD',
    confidence: 45,
    confidence_band: 'Medium',
  },
  {
    ticker: 'ZZZZ',
    added_at: '2026-09-14T09:15:00Z',
    signal: null,
    confidence: null,
    confidence_band: null,
  },
]

describe('WatchlistTable', () => {
  it('renders a row per watched ticker with its signal badge distinguishing BUY from HOLD', () => {
    renderWatchlistTable(items)

    const table = screen.getByRole('table', { name: 'Watchlist' })
    const rows = within(table).getAllByRole('row').slice(1)
    expect(rows).toHaveLength(3)

    // Ticker cell links into stock detail (common/TickerLink).
    expect(within(rows[0]!).getByRole('link', { name: 'AAPL' })).toHaveAttribute(
      'href',
      '/stocks/AAPL',
    )

    const aaplBadges = within(rows[0]!).getAllByTestId('signal-badge')
    expect(aaplBadges).toHaveLength(1)
    expect(aaplBadges[0]).toHaveTextContent('BUY')

    const msftBadges = within(rows[1]!).getAllByTestId('signal-badge')
    expect(msftBadges[0]).toHaveTextContent('HOLD')

    // The two badges resolve to visually distinct colors (BUY vs. HOLD),
    // reusing common/SignalBadge's own color convention rather than a
    // second one — same assertion style SignalBadge.test.tsx itself uses.
    expect(aaplBadges[0]?.getAttribute('style')).not.toBe(
      msftBadges[0]?.getAttribute('style'),
    )
  })

  it('shows the confidence gauge for a ticker with a computed signal', () => {
    renderWatchlistTable(items)

    const table = screen.getByRole('table', { name: 'Watchlist' })
    const rows = within(table).getAllByRole('row').slice(1)
    expect(within(rows[0]!).getByRole('progressbar')).toBeInTheDocument()
    expect(within(rows[0]!).getByText(/72%/)).toBeInTheDocument()
  })

  it('renders an em dash for a ticker whose signal could not be computed', () => {
    renderWatchlistTable(items)

    const table = screen.getByRole('table', { name: 'Watchlist' })
    const rows = within(table).getAllByRole('row').slice(1)
    const zzzzRow = rows[2]!

    expect(within(zzzzRow).getByText('ZZZZ')).toBeInTheDocument()
    const cells = within(zzzzRow).getAllByRole('cell')
    expect(cells.map((cell) => cell.textContent)).toContain('—')
    expect(within(zzzzRow).queryByTestId('signal-badge')).not.toBeInTheDocument()
  })

  it('renders the empty state when the watchlist has no tickers', () => {
    renderWatchlistTable([])

    expect(
      screen.getByText('Your watchlist is empty. Add a ticker to get started.'),
    ).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('opens a confirm dialog before removing, and cancels without removing', async () => {
    const user = userEvent.setup()
    renderWatchlistTable(items)

    await user.click(screen.getByRole('button', { name: 'Remove AAPL' }))

    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByText(/remove aapl from your watchlist/i)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Cancel' }))

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('removes the ticker on confirm', async () => {
    const user = userEvent.setup()
    renderWatchlistTable(items)

    await user.click(screen.getByRole('button', { name: 'Remove AAPL' }))
    await user.click(screen.getByRole('button', { name: 'Remove' }))

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('disables the row Remove button while its removal is pending, preventing a double-click race', async () => {
    // Delays the DELETE response so the pending window is observable -- without this the
    // mutation settles before the second click assertion below could ever run.
    let resolveDelete: () => void = () => {}
    server.use(
      http.delete('/api/watchlist/:ticker', async () => {
        await new Promise<void>((resolve) => {
          resolveDelete = resolve
        })
        return new HttpResponse(null, { status: 204 })
      }),
    )
    const user = userEvent.setup()
    renderWatchlistTable(items)

    await user.click(screen.getByRole('button', { name: 'Remove AAPL' }))
    await user.click(screen.getByRole('button', { name: 'Remove' }))

    // The confirm dialog has closed, but the DELETE is still in flight (deliberately held
    // open above) -- the row's own Remove icon button must be disabled for exactly this
    // window, otherwise a fast second click reopens the confirm dialog and fires a second
    // DELETE for the same ticker before the first has been reflected in a refetch.
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Remove AAPL' })).toBeDisabled(),
    )
    // A row unrelated to the in-flight removal stays interactive.
    expect(screen.getByRole('button', { name: 'Remove MSFT' })).not.toBeDisabled()

    resolveDelete()
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: 'Remove AAPL' })).not.toBeDisabled(),
    )
  })

  it('surfaces a 404 ApiError via common/ErrorState when the ticker is no longer watched', async () => {
    server.use(
      http.delete('/api/watchlist/:ticker', () =>
        HttpResponse.json({ detail: 'AAPL is not on the watchlist.' }, { status: 404 }),
      ),
    )
    const user = userEvent.setup()
    renderWatchlistTable(items)

    await user.click(screen.getByRole('button', { name: 'Remove AAPL' }))
    await user.click(screen.getByRole('button', { name: 'Remove' }))

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    expect(screen.getByText('Not found')).toBeInTheDocument()
    expect(screen.getByText('AAPL is not on the watchlist.')).toBeInTheDocument()
  })
})
