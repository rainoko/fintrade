import { fireEvent, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { delay, http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it } from 'vitest'
import type { IBKRScannerResultOut } from '../../../api/ibkr'
import type { WatchlistItemOut } from '../../../api/watchlist'
import { resetWatchlistStore } from '../../../../tests/mocks/handlers'
import { server } from '../../../../tests/mocks/server'
import { createTestQueryClient, renderWithProviders } from '../../../../tests/renderWithProviders'
import WatchlistTable from '../../watchlist/components/WatchlistTable'
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

  it('resolves two concurrent adds on different rows independently (regression, PR #243)', async () => {
    // Each row must own its own mutation instance: staggering the two rows'
    // responses (MSFT resolves before AAPL, even though AAPL is clicked
    // first) reproduces the shared-mutation bug from the review, where the
    // second row's mutate() detached the first row's observer and its
    // onSuccess never fired once its own request completed.
    //
    // The two clicks must be genuinely concurrent to exercise that race —
    // `await user.click(...)` doesn't return until React has flushed that
    // click's own state updates, which (before this fix existed) meant the
    // first click's mocked response, and its onSuccess, had already resolved
    // before this test even dispatched the second click. That made the
    // original version of this test pass against both the buggy pre-fix code
    // and the fix, proving nothing. `fireEvent.click` fires the DOM event
    // synchronously and returns immediately (no promise to await), so both
    // clicks are dispatched — and both POSTs in flight — before either
    // mocked response resolves.
    server.use(
      http.post('/api/watchlist', async ({ request }) => {
        const body = (await request.json()) as { ticker: string }
        await delay(body.ticker === 'AAPL' ? 40 : 10)
        return HttpResponse.json(
          { ticker: body.ticker, added_at: new Date().toISOString(), signal: null, confidence: null, confidence_band: null },
          { status: 201 },
        )
      }),
    )
    renderResultsTable(results)

    const addButtons = screen.getAllByRole('button', { name: 'Add to watchlist' })
    fireEvent.click(addButtons[0])
    fireEvent.click(addButtons[1])

    await waitFor(() =>
      expect(screen.getAllByRole('button', { name: 'Added' })).toHaveLength(2),
    )
    expect(screen.queryByRole('button', { name: 'Add to watchlist' })).not.toBeInTheDocument()
  })

  it('surfaces an add-to-watchlist failure as a compact inline retry icon, not full-block ErrorState', async () => {
    server.use(
      http.post('/api/watchlist', () =>
        HttpResponse.json({ detail: 'Something went wrong.' }, { status: 422 }),
      ),
    )
    const user = userEvent.setup()
    renderResultsTable(results)

    await user.click(screen.getAllByRole('button', { name: 'Add to watchlist' })[0])

    const retryButton = await screen.findByRole('button', {
      name: 'Retry adding AAPL to watchlist',
    })
    // Not the full ErrorState block: no alert-role landmark, and the second
    // row's own button is untouched.
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Add to watchlist' })).toBeInTheDocument()

    await user.hover(retryButton)
    expect(await screen.findByText('Something went wrong. Click to retry.')).toBeInTheDocument()

    // Clicking the icon retries the same add.
    server.use(
      http.post('/api/watchlist', () =>
        HttpResponse.json(
          { ticker: 'AAPL', added_at: new Date().toISOString(), signal: null, confidence: null, confidence_band: null },
          { status: 201 },
        ),
      ),
    )
    await user.click(retryButton)

    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Added' })).toBeInTheDocument(),
    )
  })

  it('keeps focus on the same control through a failed add and a successful retry (regression, PR #243 rounds 4-5)', async () => {
    // Round 3's fix (compact inline retry icon) swapped <Button> for a
    // different <IconButton> element on failure -- React unmounts the
    // focused node and mounts a new one, dropping keyboard focus to
    // document.body. Round 4 patched that isError false->true transition
    // with a useEffect, but the *reverse* isError true->false transition --
    // which fires on every retry click, since mutate() resets isError
    // synchronously -- reintroduced the exact same bug on the common,
    // successful-retry path (round-4 review finding). This test asserts on
    // both transitions and on the *same* underlying DOM node throughout, not
    // just "focus isn't on document.body" -- the fix here renders exactly
    // one persistent <Button> across every state instead of two different
    // element types, so `addButton`/`retryButton`/`addedButton` below are all
    // required to be the exact same node.
    server.use(
      http.post('/api/watchlist', () =>
        HttpResponse.json({ detail: 'Something went wrong.' }, { status: 422 }),
      ),
    )
    const user = userEvent.setup()
    renderResultsTable(results)

    const addButton = screen.getAllByRole('button', { name: 'Add to watchlist' })[0]
    addButton.focus()
    await user.click(addButton)

    const retryButton = await screen.findByRole('button', {
      name: 'Retry adding AAPL to watchlist',
    })
    expect(retryButton).toBe(addButton)
    await waitFor(() => expect(document.activeElement).toBe(retryButton))

    server.use(
      http.post('/api/watchlist', () =>
        HttpResponse.json(
          { ticker: 'AAPL', added_at: new Date().toISOString(), signal: null, confidence: null, confidence_band: null },
          { status: 201 },
        ),
      ),
    )
    await user.click(retryButton)

    const addedButton = await screen.findByRole('button', { name: 'Added' })
    expect(addedButton).toBe(retryButton)
    await waitFor(() => expect(document.activeElement).toBe(addedButton))
  })

  it('announces a failed add via a live region, even for a user not focused on that row (regression, PR #243 round 4)', async () => {
    // role="status" doesn't support "name from content" (ARIA accname spec),
    // so this asserts on the live region's textContent rather than its
    // accessible name.
    server.use(
      http.post('/api/watchlist', () =>
        HttpResponse.json({ detail: 'Something went wrong.' }, { status: 422 }),
      ),
    )
    const user = userEvent.setup()
    renderResultsTable(results)

    // No announcement before anything fails -- one silent live region per row.
    expect(screen.getAllByRole('status').map((el) => el.textContent)).toEqual(['', ''])

    await user.click(screen.getAllByRole('button', { name: 'Add to watchlist' })[0])
    await screen.findByRole('button', { name: 'Retry adding AAPL to watchlist' })

    await waitFor(() => {
      expect(screen.getAllByRole('status').map((el) => el.textContent)).toContain(
        'Failed to add AAPL to watchlist: Something went wrong.',
      )
    })
  })

  it('does not bleed a pending Scanner-page add into WatchlistTable as a phantom skeleton row (regression, PR #243 round 4)', async () => {
    // WatchlistTable's own useMutationState reads useAddWatchlistItem's
    // shared mutation-cache entry (keyed by watchlistKeys.add) to render a
    // pending-add skeleton row for its own AddTickerForm. Both components are
    // mounted here under one shared QueryClient -- mirroring the real app's
    // single app-wide QueryClient (main.tsx) spanning every page/route, not
    // two independent per-test clients -- so a Scanner-dispatched add that
    // reuses the same mutation key would otherwise be indistinguishable, from
    // WatchlistTable's point of view, from an add dispatched by its own
    // AddTickerForm sibling.
    let resolvePost: (value: WatchlistItemOut) => void = () => {}
    server.use(
      http.post('/api/watchlist', async () => {
        const created = await new Promise<WatchlistItemOut>((resolve) => {
          resolvePost = resolve
        })
        return HttpResponse.json(created, { status: 201 })
      }),
    )
    const queryClient = createTestQueryClient()
    const user = userEvent.setup()

    renderWithProviders(
      <MemoryRouter>
        <ScannerResultsTable results={results} />
        <WatchlistTable items={[]} />
      </MemoryRouter>,
      { queryClient },
    )

    await user.click(screen.getAllByRole('button', { name: 'Add to watchlist' })[0])

    // Confirms the add is genuinely pending (not yet settled) before
    // asserting the negative below -- the Scanner row's own button renders a
    // CircularProgress icon while addWatchlistItem.isPending is true.
    await waitFor(() => expect(screen.getByRole('progressbar')).toBeInTheDocument())
    expect(screen.queryByTestId('watchlist-skeleton')).not.toBeInTheDocument()

    resolvePost({
      ticker: 'AAPL',
      added_at: new Date().toISOString(),
      signal: null,
      confidence: null,
      confidence_band: null,
    })
    await waitFor(() =>
      expect(screen.getAllByRole('button', { name: 'Added' })).toHaveLength(1),
    )
    expect(screen.queryByTestId('watchlist-skeleton')).not.toBeInTheDocument()
  })
})
