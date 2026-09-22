import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { IBKRBreadthSnapshotResponse } from '../../../api/ibkr'
import { server } from '../../../../tests/mocks/server'
import { renderWithProviders } from '../../../../tests/renderWithProviders'
import MarketBreadthCard from './MarketBreadthCard'

function mockBreadthSnapshot(responses: Record<'adv' | 'dec', IBKRBreadthSnapshotResponse>) {
  server.use(
    http.post('/api/ibkr/breadth/snapshot', async ({ request }) => {
      const body = (await request.json()) as { series_key: 'adv' | 'dec' }
      return HttpResponse.json(responses[body.series_key])
    }),
  )
}

const availableAdvance: IBKRBreadthSnapshotResponse = {
  state: 'available',
  detail: null,
  series_key: 'adv',
  snapshot_date: '2026-09-22',
  count: 42,
  days_recorded: 20,
  rolling_5d: 210,
  rolling_20d: 800,
}

const availableDecline: IBKRBreadthSnapshotResponse = {
  state: 'available',
  detail: null,
  series_key: 'dec',
  snapshot_date: '2026-09-22',
  count: 17,
  days_recorded: 20,
  rolling_5d: 90,
  rolling_20d: 650,
}

describe('MarketBreadthCard', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('shows a loading state, then a non-error disabled panel when IBKR is disabled (the default MSW handler)', async () => {
    renderWithProviders(<MarketBreadthCard />)

    expect(screen.getByText('Loading market breadth...')).toBeInTheDocument()

    await waitFor(() =>
      expect(
        screen.getByText(
          "Real market breadth isn't available right now — it needs the optional IBKR Client Portal Gateway integration connected.",
        ),
      ).toBeInTheDocument(),
    )
    expect(screen.getByText('IBKR: Disabled')).toBeInTheDocument()
    expect(screen.queryByText('Top % Gainers (today)')).not.toBeInTheDocument()
  })

  it('shows a distinct disabled panel for gateway_unreachable, using the returned detail', async () => {
    mockBreadthSnapshot({
      adv: {
        state: 'gateway_unreachable',
        detail: 'IBKR gateway request to /iserver/auth/status failed',
        series_key: 'adv',
        snapshot_date: null,
        count: null,
        days_recorded: 0,
        rolling_5d: null,
        rolling_20d: null,
      },
      dec: {
        state: 'gateway_unreachable',
        detail: 'IBKR gateway request to /iserver/auth/status failed',
        series_key: 'dec',
        snapshot_date: null,
        count: null,
        days_recorded: 0,
        rolling_5d: null,
        rolling_20d: null,
      },
    })

    renderWithProviders(<MarketBreadthCard />)

    await waitFor(() => expect(screen.getByText('IBKR: Gateway down')).toBeInTheDocument())
  })

  it('falls back to the decline snapshot\'s unavailable state when only it (not the advance snapshot) reports unavailable', async () => {
    mockBreadthSnapshot({
      adv: availableAdvance,
      dec: {
        state: 'not_authenticated',
        detail: 'please log in',
        series_key: 'dec',
        snapshot_date: null,
        count: null,
        days_recorded: 0,
        rolling_5d: null,
        rolling_20d: null,
      },
    })

    renderWithProviders(<MarketBreadthCard />)

    await waitFor(() => expect(screen.getByText('IBKR: Sign-in needed')).toBeInTheDocument())
    expect(screen.queryByText('Top % Gainers (today)')).not.toBeInTheDocument()
  })

  it('renders the advance/decline counts and rolling spreads once available with a full 20-day history', async () => {
    mockBreadthSnapshot({ adv: availableAdvance, dec: availableDecline })

    renderWithProviders(<MarketBreadthCard />)

    await waitFor(() => expect(screen.getByText('Top % Gainers (today)')).toBeInTheDocument())
    expect(screen.getByText('42')).toBeInTheDocument()
    expect(screen.getByText('17')).toBeInTheDocument()
    // 5-day spread: 210 - 90 = +120; 20-day spread: 800 - 650 = +150.
    expect(screen.getByText('+120')).toBeInTheDocument()
    expect(screen.getByText('+150')).toBeInTheDocument()
    // Full 20-day history recorded -- no "needs more days" caption.
    expect(screen.queryByText(/days recorded so far/)).not.toBeInTheDocument()
  })

  it('renders a negative spread without a leading "+"', async () => {
    mockBreadthSnapshot({
      adv: { ...availableAdvance, rolling_5d: 50, rolling_20d: 500 },
      dec: { ...availableDecline, rolling_5d: 90, rolling_20d: 650 },
    })

    renderWithProviders(<MarketBreadthCard />)

    await waitFor(() => expect(screen.getByText('-40')).toBeInTheDocument())
    expect(screen.getByText('-150')).toBeInTheDocument()
  })

  it('shows a "—" spread plus a history-progress caption when fewer than 5 days are recorded', async () => {
    mockBreadthSnapshot({
      adv: { ...availableAdvance, days_recorded: 2, rolling_5d: null, rolling_20d: null },
      dec: { ...availableDecline, days_recorded: 2, rolling_5d: null, rolling_20d: null },
    })

    renderWithProviders(<MarketBreadthCard />)

    await waitFor(() => expect(screen.getByText('Top % Gainers (today)')).toBeInTheDocument())
    expect(screen.getAllByText('—')).toHaveLength(2)
    expect(
      screen.getByText(
        '2 of 5 days recorded so far — the 5-day spread appears once 5 days are recorded (20 for the 20-day spread).',
      ),
    ).toBeInTheDocument()
  })

  it('shows a 20-day-specific caption once the 5-day window is populated but the 20-day one is not', async () => {
    mockBreadthSnapshot({
      adv: { ...availableAdvance, days_recorded: 10, rolling_20d: null },
      dec: { ...availableDecline, days_recorded: 10, rolling_20d: null },
    })

    renderWithProviders(<MarketBreadthCard />)

    await waitFor(() =>
      expect(
        screen.getByText('10 of 20 days recorded so far — the 20-day spread appears once 20 days are recorded.'),
      ).toBeInTheDocument(),
    )
  })

  it('shows an ApiError via common/ErrorState on a genuine transport failure', async () => {
    server.use(http.post('/api/ibkr/breadth/snapshot', () => HttpResponse.error()))

    renderWithProviders(<MarketBreadthCard />)

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    expect(screen.getByText('Connection error')).toBeInTheDocument()
  })

  it('opens the Market Breadth help balloon with the honest IBKR-scanner-approximation framing and the current reading', async () => {
    mockBreadthSnapshot({ adv: availableAdvance, dec: availableDecline })
    const user = userEvent.setup()

    renderWithProviders(<MarketBreadthCard />)

    await waitFor(() => expect(screen.getByText('Top % Gainers (today)')).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: 'Market Breadth (IBKR Scanner) help' }))

    expect(screen.getByText(/not a true full-market count/)).toBeInTheDocument()
    expect(
      screen.getByText('Today: 42 top-gainer matches vs. 17 top-loser matches. 5-day spread: +120. 20-day spread: +150.'),
    ).toBeInTheDocument()
  })

  it('retries the decline request once after Retry-After on a 429, rather than failing the whole widget', async () => {
    vi.useFakeTimers()
    let declineCallCount = 0
    server.use(
      http.post('/api/ibkr/breadth/snapshot', async ({ request }) => {
        const body = (await request.json()) as { series_key: 'adv' | 'dec' }
        if (body.series_key === 'adv') {
          return HttpResponse.json(availableAdvance)
        }
        declineCallCount += 1
        if (declineCallCount === 1) {
          return HttpResponse.json(
            { detail: 'IBKR scanner run rate-limited; retry again in 1.00s' },
            { status: 429, headers: { 'Retry-After': '1' } },
          )
        }
        return HttpResponse.json(availableDecline)
      }),
    )

    renderWithProviders(<MarketBreadthCard />)

    await vi.advanceTimersByTimeAsync(1_100)

    await vi.waitFor(() => expect(screen.getByText('Top % Gainers (today)')).toBeInTheDocument())
    expect(declineCallCount).toBe(2)
    expect(screen.getByText('17')).toBeInTheDocument()
  })
})
