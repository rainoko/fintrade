import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { HistoryResponse } from '../../../api/stocks'
import { server } from '../../../../tests/mocks/server'
import { renderWithProviders } from '../../../../tests/renderWithProviders'
import PriceChart from './PriceChart'

// jsdom has no real <canvas> 2D context, and Lightweight Charts' own
// resize/rendering internals (ResizeObserver, canvas drawing) aren't
// available/meaningful in this environment either — mocking the whole
// module is the standard way this kind of chart library gets tested (there
// is nothing pixel-level to assert on in jsdom), so these tests instead
// assert on the surrounding React behavior: the container is mounted,
// `setData` receives the right bars, and the chart is torn down/recreated
// on refetch.
const setDataMock = vi.fn()
const removeMock = vi.fn()
const fitContentMock = vi.fn()
const addSeriesMock = vi.fn(() => ({ setData: setDataMock }))
const createChartMock = vi.fn(() => ({
  addSeries: addSeriesMock,
  timeScale: () => ({ fitContent: fitContentMock }),
  remove: removeMock,
}))

vi.mock('lightweight-charts', () => ({
  createChart: () => createChartMock(),
  CandlestickSeries: 'CandlestickSeries-definition',
}))

function mockHistory(response: HistoryResponse) {
  server.use(http.get('/api/stocks/:ticker/history', () => HttpResponse.json(response)))
}

// GET /api/stocks/{ticker}/history legitimately returns null
// open/high/low/close for today's still-forming (not yet closed) trading
// day whenever the query window reaches it (yfinance NaN OHLC, serialized
// as JSON null) — even though the generated `HistoryResponse['bars']` type
// says `number`, since that's what the real backend does. Built via a
// single cast (rather than `as any` on each of the four fields) to
// construct that real-world shape for tests despite the type.
const formingBar = {
  date: '2026-09-03',
  open: null,
  high: null,
  low: null,
  close: null,
  volume: 12345,
} as unknown as HistoryResponse['bars'][number]

const twoBars: HistoryResponse = {
  ticker: 'AAPL',
  interval: 'daily',
  bars: [
    {
      date: '2026-09-01',
      open: 227.1,
      high: 229.4,
      low: 226.8,
      close: 228.9,
      volume: 51234000,
    },
    {
      date: '2026-09-02',
      open: 228.9,
      high: 230.1,
      low: 227.5,
      close: 229.7,
      volume: 48012000,
    },
  ],
}

describe('PriceChart', () => {
  beforeEach(() => {
    setDataMock.mockClear()
    removeMock.mockClear()
    fitContentMock.mockClear()
    addSeriesMock.mockClear()
    createChartMock.mockClear()
  })

  it('shows a loading state, then renders the candlestick chart from the bars returned', async () => {
    mockHistory(twoBars)

    renderWithProviders(<PriceChart ticker="AAPL" />)

    expect(screen.getByText('Loading price history for AAPL...')).toBeInTheDocument()

    await waitFor(() =>
      expect(screen.getByTestId('price-chart-canvas')).toBeInTheDocument(),
    )

    expect(createChartMock).toHaveBeenCalledTimes(1)
    expect(setDataMock).toHaveBeenCalledWith([
      { time: '2026-09-01', open: 227.1, high: 229.4, low: 226.8, close: 228.9 },
      { time: '2026-09-02', open: 228.9, high: 230.1, low: 227.5, close: 229.7 },
    ])
    expect(fitContentMock).toHaveBeenCalledTimes(1)
  })

  it('filters out a still-forming bar with null OHLC values before calling setData', async () => {
    // The chart must drop the forming bar rather than pass it straight to
    // Lightweight Charts, which throws synchronously on a non-numeric value
    // and would otherwise crash the whole page (see hasFiniteOhlc in
    // PriceChart.tsx).
    mockHistory({
      ticker: 'AAPL',
      interval: 'daily',
      bars: [...twoBars.bars, formingBar],
    })

    renderWithProviders(<PriceChart ticker="AAPL" />)

    await waitFor(() =>
      expect(screen.getByTestId('price-chart-canvas')).toBeInTheDocument(),
    )

    expect(setDataMock).toHaveBeenCalledWith([
      { time: '2026-09-01', open: 227.1, high: 229.4, low: 226.8, close: 228.9 },
      { time: '2026-09-02', open: 228.9, high: 230.1, low: 227.5, close: 229.7 },
    ])
  })

  it('shows an EmptyState instead of a broken chart when every bar has null OHLC values', async () => {
    mockHistory({
      ticker: 'AAPL',
      interval: 'daily',
      bars: [formingBar],
    })

    renderWithProviders(<PriceChart ticker="AAPL" />)

    await waitFor(() =>
      expect(
        screen.getByText('No price history available for AAPL.'),
      ).toBeInTheDocument(),
    )
    expect(screen.queryByTestId('price-chart-canvas')).not.toBeInTheDocument()
    expect(createChartMock).not.toHaveBeenCalled()
  })

  it('shows an EmptyState instead of a broken chart when the API returns zero bars', async () => {
    mockHistory({ ticker: 'AAPL', interval: 'daily', bars: [] })

    renderWithProviders(<PriceChart ticker="AAPL" />)

    await waitFor(() =>
      expect(
        screen.getByText('No price history available for AAPL.'),
      ).toBeInTheDocument(),
    )
    expect(screen.queryByTestId('price-chart-canvas')).not.toBeInTheDocument()
    expect(createChartMock).not.toHaveBeenCalled()
  })

  it('refetches with the selected range when a range preset is clicked', async () => {
    const user = userEvent.setup()
    let lastRequestedRange: string | null = null
    server.use(
      http.get('/api/stocks/:ticker/history', ({ request }) => {
        lastRequestedRange = new URL(request.url).searchParams.get('range')
        return HttpResponse.json(twoBars)
      }),
    )

    renderWithProviders(<PriceChart ticker="AAPL" />)

    await waitFor(() =>
      expect(screen.getByTestId('price-chart-canvas')).toBeInTheDocument(),
    )
    expect(lastRequestedRange).toBe('1y')

    const rangeGroup = screen.getByRole('group', { name: 'Price history range' })
    await user.click(within(rangeGroup).getByRole('button', { name: '3M' }))

    await waitFor(() => expect(lastRequestedRange).toBe('3m'))
    // A new range means a new query, so the chart is recreated rather than
    // patched in place.
    await waitFor(() => expect(createChartMock).toHaveBeenCalledTimes(2))
    expect(removeMock).toHaveBeenCalledTimes(1)

    // MUI's exclusive ToggleButtonGroup reports `null` when the
    // already-selected button is clicked again — that must be a no-op
    // (never clear the selection/refetch with an empty range).
    createChartMock.mockClear()
    await user.click(within(rangeGroup).getByRole('button', { name: '3M' }))
    expect(lastRequestedRange).toBe('3m')
    expect(createChartMock).not.toHaveBeenCalled()
  })

  it('refetches with the selected interval when the Weekly toggle is clicked', async () => {
    let lastRequestedInterval: string | null = null
    server.use(
      http.get('/api/stocks/:ticker/history', ({ request }) => {
        lastRequestedInterval = new URL(request.url).searchParams.get('interval')
        return HttpResponse.json({ ...twoBars, interval: 'weekly' })
      }),
    )
    const user = userEvent.setup()

    renderWithProviders(<PriceChart ticker="AAPL" />)

    await waitFor(() =>
      expect(screen.getByTestId('price-chart-canvas')).toBeInTheDocument(),
    )
    expect(lastRequestedInterval).toBe('daily')

    const intervalGroup = screen.getByRole('group', { name: 'Price history interval' })
    await user.click(within(intervalGroup).getByRole('button', { name: 'Weekly' }))

    await waitFor(() => expect(lastRequestedInterval).toBe('weekly'))

    // Re-clicking the already-selected interval reports `null` (MUI's
    // exclusive-group behavior) and must be a no-op, same as the range
    // selector above.
    await user.click(within(intervalGroup).getByRole('button', { name: 'Weekly' }))
    expect(lastRequestedInterval).toBe('weekly')
  })

  it('shows the unrecognized-range 422 distinctly via common/ErrorState', async () => {
    // PriceChart's own UI only ever sends one of the fixed RANGE_OPTIONS
    // presets, all of which match the backend's pattern — this simulates
    // the case at the handler level (docs/architecture/API.md's two
    // distinct 422 cases for this endpoint) the same way an out-of-band
    // range would be rejected.
    server.use(
      http.get('/api/stocks/:ticker/history', () =>
        HttpResponse.json(
          {
            detail: [
              {
                loc: ['query', 'range'],
                msg: "String should match pattern '^(max|\\d{1,4}[dwmy])$'",
                type: 'string_pattern_mismatch',
              },
            ],
          },
          { status: 422 },
        ),
      ),
    )

    renderWithProviders(<PriceChart ticker="AAPL" />)

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    expect(screen.getByText('Unable to process request')).toBeInTheDocument()
    expect(
      screen.getByText("String should match pattern '^(max|\\d{1,4}[dwmy])$'"),
    ).toBeInTheDocument()
  })

  it('shows the insufficient-weekly-history 422 distinctly via common/ErrorState', async () => {
    server.use(
      http.get('/api/stocks/:ticker/history', ({ request }) => {
        const interval = new URL(request.url).searchParams.get('interval')
        if (interval === 'weekly') {
          return HttpResponse.json(
            { detail: 'Insufficient weekly history for THINHISTORY (< 26 weeks).' },
            { status: 422 },
          )
        }
        return HttpResponse.json(twoBars)
      }),
    )
    const user = userEvent.setup()

    renderWithProviders(<PriceChart ticker="THINHISTORY" />)

    await waitFor(() =>
      expect(screen.getByTestId('price-chart-canvas')).toBeInTheDocument(),
    )

    const intervalGroup = screen.getByRole('group', { name: 'Price history interval' })
    await user.click(within(intervalGroup).getByRole('button', { name: 'Weekly' }))

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    expect(screen.getByText('Unable to process request')).toBeInTheDocument()
    expect(
      screen.getByText('Insufficient weekly history for THINHISTORY (< 26 weeks).'),
    ).toBeInTheDocument()
  })

  it('shows a 404 error via common/ErrorState for an unknown ticker', async () => {
    renderWithProviders(<PriceChart ticker="UNKNOWN" />)

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    expect(screen.getByText('Not found')).toBeInTheDocument()
  })
})
