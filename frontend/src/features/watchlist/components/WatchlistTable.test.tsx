import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import type { WatchlistItemOut } from '../../../api/watchlist'
import { server } from '../../../../tests/mocks/server'
import { renderWithProviders } from '../../../../tests/renderWithProviders'
import { useAddWatchlistItem } from '../hooks/useAddWatchlistItem'
import WatchlistTable, { type WatchlistTableProps } from './WatchlistTable'

function renderWatchlistTable(items: WatchlistTableProps['items']) {
  return renderWithProviders(
    <MemoryRouter>
      <WatchlistTable items={items} />
    </MemoryRouter>,
  )
}

/**
 * Drives WatchlistTable's skeleton-row rendering directly off a real
 * useAddWatchlistItem mutation (the same shared mutation-cache entry
 * WatchlistPage's real AddTickerForm+WatchlistTable pairing would produce),
 * without needing AddTickerForm/the input field at all -- a plain trigger
 * button calling `.mutate` is enough to exercise WatchlistTable's own
 * pending-ticker-derivation and per-column skeleton branches in isolation.
 */
function TriggerAddHarness({ items, ticker }: { items: WatchlistItemOut[]; ticker: string }) {
  const addWatchlistItem = useAddWatchlistItem()
  return (
    <MemoryRouter>
      <button onClick={() => addWatchlistItem.mutate({ ticker })}>trigger-add</button>
      <WatchlistTable items={items} />
    </MemoryRouter>
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

  it('renders an animated skeleton placeholder row for a ticker currently being added, then the real row once it appears in items', async () => {
    let resolvePost: (value: WatchlistItemOut) => void = () => {}
    server.use(
      http.post('/api/watchlist', async () => {
        const created = await new Promise<WatchlistItemOut>((resolve) => {
          resolvePost = resolve
        })
        return HttpResponse.json(created, { status: 201 })
      }),
    )
    const user = userEvent.setup()
    const { rerender } = renderWithProviders(
      <TriggerAddHarness items={items} ticker="TSLA" />,
    )

    await user.click(screen.getByRole('button', { name: 'trigger-add' }))

    await waitFor(() =>
      expect(screen.getAllByTestId('watchlist-skeleton').length).toBeGreaterThan(0),
    )
    const table = screen.getByRole('table', { name: 'Watchlist' })
    // The skeleton row's own action column has no Remove button (nothing to
    // remove yet), and its ticker cell is a Skeleton, not TSLA text/a link.
    expect(within(table).queryByRole('link', { name: 'TSLA' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Remove TSLA' })).not.toBeInTheDocument()

    resolvePost({
      ticker: 'TSLA',
      added_at: '2026-09-19T00:00:00Z',
      signal: null,
      confidence: null,
      confidence_band: null,
    })
    // The mutation settles, but `items` (this harness's own static prop)
    // never actually gains TSLA -- exactly like WatchlistTable's real usage
    // under WatchlistPage, where the pending-ticker signal disappears (its
    // mutation is no longer 'pending') independently of whether a rerender
    // carries fresh `items`. Re-rendering with TSLA now included in `items`
    // is what a real refetch would supply.
    await waitFor(() =>
      expect(screen.queryByTestId('watchlist-skeleton')).not.toBeInTheDocument(),
    )
    rerender(
      <TriggerAddHarness
        items={[
          ...items,
          {
            ticker: 'TSLA',
            added_at: '2026-09-19T00:00:00Z',
            signal: null,
            confidence: null,
            confidence_band: null,
          },
        ]}
        ticker="TSLA"
      />,
    )
    expect(within(table).getByText('TSLA')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Remove TSLA' })).toBeInTheDocument()
  })

  it('does not render a skeleton row for a pending add whose ticker is already present in items (idempotent no-op)', async () => {
    let resolvePost: (value: WatchlistItemOut) => void = () => {}
    server.use(
      http.post('/api/watchlist', async () => {
        const created = await new Promise<WatchlistItemOut>((resolve) => {
          resolvePost = resolve
        })
        return HttpResponse.json(created, { status: 201 })
      }),
    )
    const user = userEvent.setup()
    renderWithProviders(<TriggerAddHarness items={items} ticker="AAPL" />)

    await user.click(screen.getByRole('button', { name: 'trigger-add' }))

    // Give the pending mutation a chance to be observed -- there is
    // deliberately no skeleton to wait for, since AAPL's real row is
    // already in `items`.
    await waitFor(() => expect(screen.getByRole('button', { name: 'trigger-add' })).toBeInTheDocument())
    expect(screen.queryByTestId('watchlist-skeleton')).not.toBeInTheDocument()
    const table = screen.getByRole('table', { name: 'Watchlist' })
    expect(within(table).getAllByText('AAPL')).toHaveLength(1)

    resolvePost({
      ticker: 'AAPL',
      added_at: '2026-09-10T09:15:00Z',
      signal: 'BUY',
      confidence: 72,
      confidence_band: 'High',
    })
    await waitFor(() => expect(screen.queryByTestId('watchlist-skeleton')).not.toBeInTheDocument())
  })

  it('keeps the pending skeleton row sorted at the "newest" end of the Added column instead of jumping', async () => {
    // Every existing row's `added_at` is a fixed date well in the past, so
    // the skeleton row (sorted by its mutation's own `submittedAt`, which is
    // effectively "now") always sorts as the newest entry -- last ascending,
    // first descending -- exactly where the real row will land once it
    // replaces the skeleton, so its position never jumps across that swap.
    server.use(
      http.post('/api/watchlist', () => new Promise(() => {})), // never resolves; only the pending state matters here
    )
    const user = userEvent.setup()
    renderWithProviders(<TriggerAddHarness items={items} ticker="TSLA" />)

    await user.click(screen.getByRole('button', { name: 'trigger-add' }))
    await waitFor(() =>
      expect(screen.getAllByTestId('watchlist-skeleton').length).toBeGreaterThan(0),
    )

    const table = screen.getByRole('table', { name: 'Watchlist' })
    const getDataRows = () => within(table).getAllByRole('row').slice(1)
    const skeletonRowIndex = () =>
      getDataRows().findIndex(
        (row) => within(row).queryAllByTestId('watchlist-skeleton').length > 0,
      )

    // Default sort is unsorted (GET's own oldest-first order); the pending
    // row is appended last regardless.
    expect(skeletonRowIndex()).toBe(getDataRows().length - 1)

    // Ascending "Added" sort (the table's default direction on first click):
    // the skeleton, sorting as "now", is still the newest -> still last.
    await user.click(screen.getByRole('button', { name: 'Added' }))
    expect(skeletonRowIndex()).toBe(getDataRows().length - 1)

    // Descending: the newest sorts first, so the skeleton moves to the top
    // -- not to some arbitrary middle position, and it stays there (rather
    // than reordering again) once the real row eventually replaces it.
    await user.click(screen.getByRole('button', { name: 'Added' }))
    expect(skeletonRowIndex()).toBe(0)
  })
})
