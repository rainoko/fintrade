import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import type { BreadthResponse } from '../../../api/watchlist'
import { server } from '../../../../tests/mocks/server'
import { renderWithProviders } from '../../../../tests/renderWithProviders'
import PersonalBreadthCard from './PersonalBreadthCard'

function mockBreadth(response: BreadthResponse) {
  server.use(http.get('/api/watchlist/breadth', () => HttpResponse.json(response)))
}

describe('PersonalBreadthCard', () => {
  it('shows a loading state, then the BULLISH/BEARISH/NEUTRAL breakdown for a mixed tracked universe, with no unavailable footnote when none are unavailable', async () => {
    mockBreadth({
      tracked_ticker_count: 4,
      bullish_count: 2,
      bearish_count: 1,
      neutral_count: 1,
      unavailable_count: 0,
      bullish_pct: 50.0,
      bearish_pct: 25.0,
      neutral_pct: 25.0,
    })

    renderWithProviders(<PersonalBreadthCard />)

    await waitFor(() => expect(screen.getByText('Bearish')).toBeInTheDocument())
    expect(screen.getAllByText('1 (25.0%)')).toHaveLength(2)
    expect(screen.getByText('Neutral')).toBeInTheDocument()
    expect(screen.queryByText(/currently unavailable/)).not.toBeInTheDocument()
  })

  it('shows an unavailable-count footnote when some tracked tickers have no computable Tide trend', async () => {
    mockBreadth({
      tracked_ticker_count: 5,
      bullish_count: 2,
      bearish_count: 1,
      neutral_count: 1,
      unavailable_count: 1,
      bullish_pct: 50.0,
      bearish_pct: 25.0,
      neutral_pct: 25.0,
    })

    renderWithProviders(<PersonalBreadthCard />)

    await waitFor(() =>
      expect(
        screen.getByText('1 of 5 tracked tickers currently unavailable (excluded above).'),
      ).toBeInTheDocument(),
    )
  })

  it('pluralizes the unavailable-count footnote for more than one unavailable ticker', async () => {
    mockBreadth({
      tracked_ticker_count: 6,
      bullish_count: 2,
      bearish_count: 1,
      neutral_count: 1,
      unavailable_count: 2,
      bullish_pct: 50.0,
      bearish_pct: 25.0,
      neutral_pct: 25.0,
    })

    renderWithProviders(<PersonalBreadthCard />)

    await waitFor(() =>
      expect(
        screen.getByText(
          '2 of 6 tracked tickers currently unavailable (excluded above).',
        ),
      ).toBeInTheDocument(),
    )
  })

  it('shows an empty state when nothing is tracked yet, rather than three zero-value stats', async () => {
    mockBreadth({
      tracked_ticker_count: 0,
      bullish_count: 0,
      bearish_count: 0,
      neutral_count: 0,
      unavailable_count: 0,
      bullish_pct: 0,
      bearish_pct: 0,
      neutral_pct: 0,
    })

    renderWithProviders(<PersonalBreadthCard />)

    await waitFor(() =>
      expect(
        screen.getByText(
          'Add a ticker to your watchlist or portfolio to see a personal breadth breakdown.',
        ),
      ).toBeInTheDocument(),
    )
    expect(screen.queryByText('Bullish')).not.toBeInTheDocument()
  })

  it('shows an ApiError via common/ErrorState on failure', async () => {
    server.use(
      http.get('/api/watchlist/breadth', () =>
        HttpResponse.json({ detail: 'boom' }, { status: 500 }),
      ),
    )

    renderWithProviders(<PersonalBreadthCard />)

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    expect(screen.getByText('Something went wrong')).toBeInTheDocument()
  })

  it('opens the Personal Breadth help balloon with the honest personal-proxy framing and the current breakdown', async () => {
    mockBreadth({
      tracked_ticker_count: 4,
      bullish_count: 2,
      bearish_count: 1,
      neutral_count: 1,
      unavailable_count: 0,
      bullish_pct: 50.0,
      bearish_pct: 25.0,
      neutral_pct: 25.0,
    })
    const user = userEvent.setup()

    renderWithProviders(<PersonalBreadthCard />)

    await waitFor(() => expect(screen.getByText('Bullish')).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: 'Personal Breadth help' }))

    expect(
      screen.getByText(/whose weekly Screen 1 \(Tide\) trend is currently/),
    ).toBeInTheDocument()
    expect(screen.getByText(/not true market breadth/)).toBeInTheDocument()
    expect(
      screen.getByText(
        '2 of 4 computable tickers (50.0%) are currently BULLISH, 1 (25.0%) BEARISH, 1 (25.0%) NEUTRAL.',
      ),
    ).toBeInTheDocument()
  })

  it('names the all-unavailable case explicitly in the help balloon rather than a generic zero', async () => {
    mockBreadth({
      tracked_ticker_count: 2,
      bullish_count: 0,
      bearish_count: 0,
      neutral_count: 0,
      unavailable_count: 2,
      bullish_pct: 0,
      bearish_pct: 0,
      neutral_pct: 0,
    })
    const user = userEvent.setup()

    renderWithProviders(<PersonalBreadthCard />)

    await waitFor(() =>
      expect(
        screen.getByText(
          '2 of 2 tracked tickers currently unavailable (excluded above).',
        ),
      ).toBeInTheDocument(),
    )
    await user.click(screen.getByRole('button', { name: 'Personal Breadth help' }))

    expect(
      screen.getByText(
        'None of your 2 tracked tickers has a computable Tide trend right now.',
      ),
    ).toBeInTheDocument()
  })

  it('uses singular wording when exactly one tracked ticker has no computable trend at all', async () => {
    mockBreadth({
      tracked_ticker_count: 1,
      bullish_count: 0,
      bearish_count: 0,
      neutral_count: 0,
      unavailable_count: 1,
      bullish_pct: 0,
      bearish_pct: 0,
      neutral_pct: 0,
    })
    const user = userEvent.setup()

    renderWithProviders(<PersonalBreadthCard />)

    await waitFor(() =>
      expect(
        screen.getByText('1 of 1 tracked ticker currently unavailable (excluded above).'),
      ).toBeInTheDocument(),
    )
    await user.click(screen.getByRole('button', { name: 'Personal Breadth help' }))

    expect(
      screen.getByText(
        'None of your 1 tracked ticker has a computable Tide trend right now.',
      ),
    ).toBeInTheDocument()
  })

  it('uses singular "ticker" wording when exactly one tracked ticker is computable', async () => {
    mockBreadth({
      tracked_ticker_count: 1,
      bullish_count: 1,
      bearish_count: 0,
      neutral_count: 0,
      unavailable_count: 0,
      bullish_pct: 100.0,
      bearish_pct: 0.0,
      neutral_pct: 0.0,
    })
    const user = userEvent.setup()

    renderWithProviders(<PersonalBreadthCard />)

    await waitFor(() => expect(screen.getByText('Bullish')).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: 'Personal Breadth help' }))

    expect(
      screen.getByText(
        '1 of 1 computable ticker (100.0%) is currently BULLISH, 0 (0.0%) BEARISH, 0 (0.0%) NEUTRAL.',
      ),
    ).toBeInTheDocument()
  })
})
