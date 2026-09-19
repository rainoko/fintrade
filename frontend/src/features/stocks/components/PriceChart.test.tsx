import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { HistoryResponse, IndicatorHistoryResponse } from '../../../api/stocks'
import { server } from '../../../../tests/mocks/server'
import {
  createTestQueryClient,
  renderWithProviders,
} from '../../../../tests/renderWithProviders'
import { stocksKeys } from '../hooks/queryKeys'
import PriceChart from './PriceChart'

// jsdom has no real <canvas> 2D context, and Lightweight Charts' own
// resize/rendering internals (ResizeObserver, canvas drawing) aren't
// available/meaningful in this environment either — mocking the whole
// module is the standard way this kind of chart library gets tested (there
// is nothing pixel-level to assert on in jsdom), so these tests instead
// assert on the surrounding React behavior: the container is mounted,
// `setData` receives the right bars, and the chart is torn down/recreated
// on refetch. `setMarkersMock`/`detachMarkersMock`/`removeSeriesMock` cover
// the EMA13/EMA26 line-series + BUY/SELL marker overlay added on top of the
// candlestick series (frontend-chart-signal-overlay).
//
// Each `createChart()` call returns a *fresh* chart object that tracks its
// own disposed state and throws from `removeSeries` once `remove()` has
// been called on it — mirroring the real Lightweight Charts library's
// `ensureDefined` throw on a disposed chart (see the reported crash: a
// previous version of PriceChart.tsx's overlay-cleanup effect called
// `chart.removeSeries(...)` on a chart the candlestick effect's cleanup had
// already disposed). A plain shared mock object that never throws wouldn't
// have caught that bug; this one does.
const setDataMock = vi.fn()
const removeMock = vi.fn()
const removeSeriesMock = vi.fn()
const fitContentMock = vi.fn()
const addSeriesMock = vi.fn(() => ({ setData: setDataMock }))
const setMarkersMock = vi.fn()
const detachMarkersMock = vi.fn()
const createSeriesMarkersMock = vi.fn((_series: unknown, markers: unknown) => {
  setMarkersMock(markers)
  return { setMarkers: setMarkersMock, markers: () => markers, detach: detachMarkersMock }
})
const createChartMock = vi.fn(() => {
  let disposed = false
  return {
    addSeries: addSeriesMock,
    removeSeries: (series: unknown) => {
      removeSeriesMock(series)
      if (disposed) {
        throw new Error('Value is undefined')
      }
    },
    timeScale: () => ({ fitContent: fitContentMock }),
    remove: () => {
      removeMock()
      disposed = true
    },
  }
})

vi.mock('lightweight-charts', () => ({
  createChart: () => createChartMock(),
  createSeriesMarkers: (series: unknown, markers: unknown) =>
    createSeriesMarkersMock(series, markers),
  CandlestickSeries: 'CandlestickSeries-definition',
  LineSeries: 'LineSeries-definition',
}))

function mockHistory(response: HistoryResponse) {
  server.use(http.get('/api/stocks/:ticker/history', () => HttpResponse.json(response)))
}

function mockIndicators(response: IndicatorHistoryResponse) {
  server.use(
    http.get('/api/stocks/:ticker/indicators', () => HttpResponse.json(response)),
  )
}

const indicatorPoints: IndicatorHistoryResponse = {
  ticker: 'AAPL',
  points: [
    {
      date: '2026-09-01',
      ema_13: 225.1,
      ema_26: 220.4,
      macd_histogram: 1.2,
      bull_power: 2.5,
      bear_power: -1.1,
      stochastic_k: 55.0,
      force_index_2ema: 1000.0,
      signal: 'HOLD',
      confidence: 0,
      confidence_band: 'Low',
    },
    {
      date: '2026-09-02',
      ema_13: 226.4,
      ema_26: 221.7,
      macd_histogram: 1.82,
      bull_power: 3.1,
      bear_power: -1.4,
      stochastic_k: 24.3,
      force_index_2ema: -18234.5,
      signal: 'BUY',
      confidence: 72,
      confidence_band: 'High',
    },
  ],
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
    removeSeriesMock.mockClear()
    fitContentMock.mockClear()
    addSeriesMock.mockClear()
    createChartMock.mockClear()
    setMarkersMock.mockClear()
    detachMarkersMock.mockClear()
    createSeriesMarkersMock.mockClear()
    mockIndicators(indicatorPoints)
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

  describe('signal overlay (GET /api/stocks/{ticker}/indicators)', () => {
    it('overlays EMA13/EMA26 line series and a marker at the bar the signal transitioned to BUY', async () => {
      mockHistory(twoBars)

      renderWithProviders(<PriceChart ticker="AAPL" />)

      await waitFor(() =>
        expect(screen.getByTestId('price-chart-canvas')).toBeInTheDocument(),
      )

      await waitFor(() => expect(createSeriesMarkersMock).toHaveBeenCalledTimes(1))

      // Candlestick + EMA13 + EMA26 = 3 addSeries calls once the overlay
      // resolves; each fed its own values straight from the backend
      // response — no client-side indicator math.
      await waitFor(() => expect(addSeriesMock).toHaveBeenCalledTimes(3))
      expect(setDataMock).toHaveBeenCalledWith([
        { time: '2026-09-01', value: 225.1 },
        { time: '2026-09-02', value: 226.4 },
      ])
      expect(setDataMock).toHaveBeenCalledWith([
        { time: '2026-09-01', value: 220.4 },
        { time: '2026-09-02', value: 221.7 },
      ])

      // The first point is HOLD (no marker) and the second transitions into
      // BUY (one marker) — not one marker per BUY-carrying bar.
      const [, markers] = createSeriesMarkersMock.mock.calls[0] as [unknown, unknown[]]
      expect(markers).toHaveLength(1)
      expect(markers[0]).toMatchObject({
        time: '2026-09-02',
        position: 'belowBar',
        shape: 'arrowUp',
        text: 'BUY',
      })
    })

    it('marks only the bar a signal transitions on, not every bar carrying that signal', async () => {
      mockHistory({
        ticker: 'AAPL',
        interval: 'daily',
        bars: [
          ...twoBars.bars,
          {
            date: '2026-09-03',
            open: 229.7,
            high: 231.0,
            low: 229.0,
            close: 230.5,
            volume: 40000000,
          },
          {
            date: '2026-09-04',
            open: 230.5,
            high: 232.0,
            low: 228.0,
            close: 228.5,
            volume: 41000000,
          },
        ],
      })
      mockIndicators({
        ticker: 'AAPL',
        points: [
          ...indicatorPoints.points,
          { ...indicatorPoints.points[1], date: '2026-09-03', signal: 'BUY' },
          { ...indicatorPoints.points[1], date: '2026-09-04', signal: 'SELL' },
        ],
      })

      renderWithProviders(<PriceChart ticker="AAPL" />)

      await waitFor(() => expect(createSeriesMarkersMock).toHaveBeenCalledTimes(1))

      const [, markers] = createSeriesMarkersMock.mock.calls[0] as [unknown, unknown[]]
      // HOLD -> BUY (2026-09-02) and BUY -> SELL (2026-09-04) transition;
      // the repeated BUY on 2026-09-03 gets no marker of its own.
      expect(markers).toHaveLength(2)
      expect(markers.map((marker) => (marker as { time: string }).time)).toEqual([
        '2026-09-02',
        '2026-09-04',
      ])
    })

    it('does not fetch or render the overlay while the Weekly interval is selected', async () => {
      let indicatorRequestCount = 0
      server.use(
        http.get('/api/stocks/:ticker/indicators', () => {
          indicatorRequestCount += 1
          return HttpResponse.json(indicatorPoints)
        }),
        http.get('/api/stocks/:ticker/history', ({ request }) => {
          const interval = new URL(request.url).searchParams.get('interval')
          return HttpResponse.json({
            ...twoBars,
            interval: (interval ?? 'daily') as 'daily' | 'weekly',
          })
        }),
      )
      const user = userEvent.setup()

      renderWithProviders(<PriceChart ticker="AAPL" />)

      await waitFor(() =>
        expect(screen.getByTestId('price-chart-canvas')).toBeInTheDocument(),
      )
      await waitFor(() => expect(indicatorRequestCount).toBe(1))
      await waitFor(() => expect(createSeriesMarkersMock).toHaveBeenCalledTimes(1))

      const intervalGroup = screen.getByRole('group', { name: 'Price history interval' })
      // Regression test for the reported crash (frontend-chart-signal-overlay
      // review): toggling the interval after the overlay has rendered once
      // used to throw synchronously from the overlay effect's cleanup
      // calling `chart.removeSeries(...)` on a chart the candlestick
      // effect's cleanup had *already* disposed via `chart.remove()` — see
      // PriceChart.tsx's decisions entry. With the mocked chart now
      // throwing in that exact scenario (see the `createChartMock` factory
      // above), this `click` would reject/throw if the guard regressed.
      await user.click(within(intervalGroup).getByRole('button', { name: 'Weekly' }))

      await waitFor(() =>
        expect(screen.getByTestId('price-chart-canvas')).toBeInTheDocument(),
      )

      // The whole prior (daily) chart is torn down via a single
      // `chart.remove()` rather than the overlay separately detaching its
      // own series/markers from it first — once a chart is removed, its own
      // series/plugins are already gone with it, so a *second*, separate
      // `removeSeries`/`detach` call against the same disposed chart isn't
      // just unnecessary, it's exactly what threw (see above). The overlay
      // cleanup's guard recognizes this (via the shared chart/series refs)
      // and skips redundant cleanup.
      expect(removeMock).toHaveBeenCalled()
      expect(detachMarkersMock).not.toHaveBeenCalled()
      expect(removeSeriesMock).not.toHaveBeenCalled()

      // No new /indicators request is made for the weekly interval — the
      // overlay is daily-only (see PriceChart.tsx's decisions entry).
      expect(indicatorRequestCount).toBe(1)
    })

    it('shows a loading state for the overlay while it is in flight, without blocking the candlestick chart', async () => {
      mockHistory(twoBars)
      let resolveIndicators: (() => void) | undefined
      server.use(
        http.get('/api/stocks/:ticker/indicators', async () => {
          await new Promise<void>((resolve) => {
            resolveIndicators = resolve
          })
          return HttpResponse.json(indicatorPoints)
        }),
      )

      renderWithProviders(<PriceChart ticker="AAPL" />)

      // The candlestick chart itself renders even though the overlay
      // request is still in flight.
      await waitFor(() =>
        expect(screen.getByTestId('price-chart-canvas')).toBeInTheDocument(),
      )
      expect(screen.getByText('Loading signal overlay for AAPL...')).toBeInTheDocument()

      resolveIndicators?.()

      await waitFor(() => expect(createSeriesMarkersMock).toHaveBeenCalledTimes(1))
      expect(
        screen.queryByText('Loading signal overlay for AAPL...'),
      ).not.toBeInTheDocument()
    })

    it('shows an ErrorState for the overlay without blocking the candlestick chart', async () => {
      mockHistory(twoBars)
      server.use(
        http.get('/api/stocks/:ticker/indicators', () =>
          HttpResponse.json(
            {
              detail: 'Market data provider is currently unavailable. Try again shortly.',
            },
            { status: 503 },
          ),
        ),
      )

      renderWithProviders(<PriceChart ticker="AAPL" />)

      // The candlestick chart itself renders even though the overlay hasn't
      // resolved yet (or has already failed) — the overlay's own state
      // (loading, then this error) never blocks it.
      await waitFor(() =>
        expect(screen.getByTestId('price-chart-canvas')).toBeInTheDocument(),
      )

      await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
      expect(screen.getByText('Service unavailable')).toBeInTheDocument()
      // The chart itself is unaffected by the overlay's failure.
      expect(screen.getByTestId('price-chart-canvas')).toBeInTheDocument()
    })

    it('swaps the overlay series in place (without recreating the candlestick chart) when only the indicators query refetches', async () => {
      // Unlike a range/interval change (which changes `historyQuery.data`
      // and recreates the whole chart), an `/indicators`-only refetch
      // leaves `historyQuery.data` referentially unchanged, so the
      // candlestick effect never re-runs and `chartRef`/`seriesRef` keep
      // pointing at the same chart — this is the path where the overlay
      // effect's cleanup guard sees matching refs and actually calls
      // `chart.removeSeries(...)`/`markersPlugin.detach()` for real (as
      // opposed to skipping because the candlestick effect already tore
      // the chart down first).
      mockHistory(twoBars)
      const queryClient = createTestQueryClient()

      renderWithProviders(<PriceChart ticker="AAPL" />, { queryClient })

      await waitFor(() => expect(createSeriesMarkersMock).toHaveBeenCalledTimes(1))
      expect(createChartMock).toHaveBeenCalledTimes(1)

      const updatedIndicators: IndicatorHistoryResponse = {
        ticker: 'AAPL',
        points: [{ ...indicatorPoints.points[1], date: '2026-09-03', signal: 'SELL' }],
      }
      mockIndicators(updatedIndicators)
      await queryClient.invalidateQueries({
        queryKey: stocksKeys.indicators('AAPL', '1y'),
      })

      await waitFor(() => expect(createSeriesMarkersMock).toHaveBeenCalledTimes(2))

      // The candlestick chart itself was never recreated...
      expect(createChartMock).toHaveBeenCalledTimes(1)
      expect(removeMock).not.toHaveBeenCalled()
      // ...but the stale overlay series/markers were removed/detached for
      // real before the new ones were added.
      expect(removeSeriesMock).toHaveBeenCalledTimes(2)
      expect(detachMarkersMock).toHaveBeenCalledTimes(1)
    })

    it('shows an EmptyState for the overlay when the API returns zero points', async () => {
      mockHistory(twoBars)
      mockIndicators({ ticker: 'AAPL', points: [] })

      renderWithProviders(<PriceChart ticker="AAPL" />)

      await waitFor(() =>
        expect(
          screen.getByText('No signal history available for AAPL.'),
        ).toBeInTheDocument(),
      )
      expect(screen.getByTestId('price-chart-canvas')).toBeInTheDocument()
      expect(createSeriesMarkersMock).not.toHaveBeenCalled()
    })
  })
})
