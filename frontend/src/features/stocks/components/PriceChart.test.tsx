import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type {
  AnalysisResponse,
  HistoryResponse,
  IndicatorHistoryResponse,
  SupportResistanceZone,
} from '../../../api/stocks'
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
//
// Each chart instance also tracks its own pane's series list (`paneSeries`)
// so `panes()[0].getSeries().length` reflects the real running count as
// `addSeries`/`removeSeries` are called — `bringSeriesToFront`
// (utils/chart.ts) reads this to compute the index it passes to the shared
// `setSeriesOrderMock` spy below, the same dynamic mechanism the real
// Lightweight Charts library's pane API provides (see this task's,
// frontend-support-resistance-overlay's, `decisions` entry for why a
// hardcoded index broke once a second effect started adding its own fill
// series to the same pane).
const setDataMock = vi.fn()
const removeMock = vi.fn()
const removeSeriesMock = vi.fn()
const fitContentMock = vi.fn()
const createPriceLineMock = vi.fn(() => ({ id: 'price-line' }))
const removePriceLineMock = vi.fn()
// `setSeriesOrder` (frontend-channel-overlay, post-review fix; made
// dynamic by frontend-support-resistance-overlay via `bringSeriesToFront`)
// is called only on the candlestick series, to reorder it above every
// fill series it's mixed in with on the same pane — see PriceChart.tsx's
// own doc comment at the call site for why. Every mock series returned by
// `addSeriesMock` gets one (matching the real `ISeriesApi`, where every
// series type has it), tracked through this one shared spy since the
// component only ever calls it on the single candlestick series it holds a
// ref to.
const setSeriesOrderMock = vi.fn()
// Typed to accept a variable number of args (`chart.addSeries(definition,
// options)` in the real library) purely so `addSeriesMock.mock.calls` below
// can be spread/destructured for assertions — this mock's own return value
// never depends on which args it was called with.
// eslint-disable-next-line @typescript-eslint/no-unused-vars
const addSeriesMock = vi.fn((..._args: unknown[]) => ({
  setData: setDataMock,
  setSeriesOrder: setSeriesOrderMock,
  createPriceLine: createPriceLineMock,
  removePriceLine: removePriceLineMock,
}))
const setMarkersMock = vi.fn()
const detachMarkersMock = vi.fn()
const createSeriesMarkersMock = vi.fn((_series: unknown, markers: unknown) => {
  setMarkersMock(markers)
  return { setMarkers: setMarkersMock, markers: () => markers, detach: detachMarkersMock }
})
const createChartMock = vi.fn(() => {
  let disposed = false
  const paneSeries: unknown[] = []
  return {
    addSeries: (...args: unknown[]) => {
      const created = addSeriesMock(...args)
      paneSeries.push(created)
      return created
    },
    removeSeries: (series: unknown) => {
      removeSeriesMock(series)
      if (disposed) {
        throw new Error('Value is undefined')
      }
      const index = paneSeries.indexOf(series)
      if (index !== -1) {
        paneSeries.splice(index, 1)
      }
    },
    panes: () => [{ getSeries: () => [...paneSeries] }],
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
  // Value-zone shading (frontend-channel-overlay) uses two `AreaSeries`;
  // channel bands use `LineStyle.Dashed` on top of the existing
  // `LineSeries-definition`. Support/resistance zone bands
  // (frontend-support-resistance-overlay) use `BaselineSeries`.
  AreaSeries: 'AreaSeries-definition',
  BaselineSeries: 'BaselineSeries-definition',
  LineStyle: { Solid: 0, Dotted: 1, Dashed: 2 },
}))

function mockHistory(response: HistoryResponse) {
  server.use(http.get('/api/stocks/:ticker/history', () => HttpResponse.json(response)))
}

function mockIndicators(response: IndicatorHistoryResponse) {
  server.use(
    http.get('/api/stocks/:ticker/indicators', () => HttpResponse.json(response)),
  )
}

// A minimal-but-complete `AnalysisResponse` for support/resistance-zone
// tests below -- only `support_resistance_zones` itself varies per test
// (via `mockAnalysis`'s `zones` param); every other field is filled with a
// plausible, unexercised value so the fixture satisfies the full generated
// type. Overrides the default MSW handler's own `analysisFixture`
// (tests/mocks/handlers.ts), which already includes one zone with no false
// breakout -- most tests below need full control over `broken`/
// `false_breakout`/`strength_score`/`role` instead.
const baseAnalysis: AnalysisResponse = {
  ticker: 'AAPL',
  as_of: '2026-09-02',
  signal: 'HOLD',
  confidence: 50,
  confidence_band: 'Medium',
  screens: {
    tide: { trend: 'NEUTRAL', weekly_macd_histogram_slope: 'flat' },
    impulse: 'BLUE',
    wave: {
      stochastic_k: 50,
      force_index_2ema: 0,
      state: 'NONE',
      showed_pullback_in_lookback: false,
      showed_rally_in_lookback: false,
    },
    trigger: { fired: false, reference: 'not_applicable' },
  },
  confidence_breakdown: [],
  indicators: {
    ema_13: 226.4,
    ema_26: 221.7,
    macd_histogram: 1.82,
    bull_power: 3.1,
    bear_power: -1.4,
  },
  support_resistance_zones: [],
}

function mockAnalysis(zones: SupportResistanceZone[]) {
  server.use(
    http.get('/api/stocks/:ticker/analysis', () =>
      HttpResponse.json({ ...baseAnalysis, support_resistance_zones: zones }),
    ),
  )
}

function buildZone(
  overrides: Partial<SupportResistanceZone> = {},
): SupportResistanceZone {
  return {
    role: 'resistance',
    upper: 236.9,
    lower: 233.4,
    first_touch_date: '2026-06-02',
    last_touch_date: '2026-08-14',
    touch_count: 3,
    length_days: 73,
    length_category: 'intermediate',
    height_pct: 1.5,
    height_category: 'minor',
    dollar_volume: 12_400_000_000,
    strength_score: 50,
    broken: false,
    break_date: null,
    false_breakout: null,
    ...overrides,
  }
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
      channel_upper: 232.0,
      channel_lower: 218.2,
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
      channel_upper: 233.3,
      channel_lower: 219.5,
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
    setSeriesOrderMock.mockClear()
    createChartMock.mockClear()
    setMarkersMock.mockClear()
    detachMarkersMock.mockClear()
    createSeriesMarkersMock.mockClear()
    createPriceLineMock.mockClear()
    removePriceLineMock.mockClear()
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

      // Candlestick + (value-zone top/bottom AreaSeries) + EMA13 + EMA26 +
      // (channel upper/lower LineSeries) + (1 support/resistance zone
      // BaselineSeries, from the default MSW /analysis fixture's single
      // zone) = 8 addSeries calls once both overlays resolve; each fed its
      // own values straight from the backend response — no client-side
      // indicator math.
      await waitFor(() => expect(addSeriesMock).toHaveBeenCalledTimes(8))
      expect(setDataMock).toHaveBeenCalledWith([
        { time: '2026-09-01', value: 225.1 },
        { time: '2026-09-02', value: 226.4 },
      ])
      expect(setDataMock).toHaveBeenCalledWith([
        { time: '2026-09-01', value: 220.4 },
        { time: '2026-09-02', value: 221.7 },
      ])
      // Value-zone top/bottom: the pointwise max/min of EMA13/EMA26 at each
      // bar (both points here have EMA13 above EMA26, so top === ema13,
      // bottom === ema26 — see the crossing case tested separately below).
      expect(setDataMock).toHaveBeenCalledWith([
        { time: '2026-09-01', value: 225.1 },
        { time: '2026-09-02', value: 226.4 },
      ])
      expect(setDataMock).toHaveBeenCalledWith([
        { time: '2026-09-01', value: 220.4 },
        { time: '2026-09-02', value: 221.7 },
      ])
      // Channel upper/lower bands straight from the backend response.
      expect(setDataMock).toHaveBeenCalledWith([
        { time: '2026-09-01', value: 232.0 },
        { time: '2026-09-02', value: 233.3 },
      ])
      expect(setDataMock).toHaveBeenCalledWith([
        { time: '2026-09-01', value: 218.2 },
        { time: '2026-09-02', value: 219.5 },
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
      // real before the new ones were added: value-zone top/bottom
      // AreaSeries, EMA13/EMA26, and channel upper/lower LineSeries -- 6
      // series total, same set `addSeriesMock`'s 7-per-overlay count above
      // includes (minus the one candlestick series, which isn't touched by
      // this cleanup at all). The support/resistance zone BaselineSeries
      // from the default /analysis fixture is untouched by this refetch
      // too -- its own effect depends on `analysisQuery.data`, not
      // `indicatorsQuery.data`, so it never re-runs/cleans up here.
      expect(removeSeriesMock).toHaveBeenCalledTimes(6)
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

  describe('channel bands + value zone (frontend-channel-overlay)', () => {
    it('computes the value zone as the pointwise max/min of EMA13/EMA26, not a fixed EMA13-is-always-on-top assumption', async () => {
      // EMA13 is above EMA26 on 09-01 (uptrend reading) but crosses below it
      // on 09-02 (downtrend reading) -- the value-zone top/bottom series
      // must track whichever EMA is actually higher at each bar, not always
      // report ema13 as the top.
      mockHistory(twoBars)
      mockIndicators({
        ticker: 'AAPL',
        points: [
          { ...indicatorPoints.points[0], ema_13: 225.1, ema_26: 220.4 },
          { ...indicatorPoints.points[1], ema_13: 219.0, ema_26: 221.7 },
        ],
      })

      renderWithProviders(<PriceChart ticker="AAPL" />)

      await waitFor(() => expect(createSeriesMarkersMock).toHaveBeenCalledTimes(1))

      expect(setDataMock).toHaveBeenCalledWith([
        { time: '2026-09-01', value: 225.1 },
        { time: '2026-09-02', value: 221.7 },
      ])
      expect(setDataMock).toHaveBeenCalledWith([
        { time: '2026-09-01', value: 220.4 },
        { time: '2026-09-02', value: 219.0 },
      ])
    })

    it('omits a bar with a null channel_upper/channel_lower from the channel band series rather than plotting a gap value', async () => {
      // A ticker still inside the Autoenvelope's ~100-trading-day warm-up
      // window reports null channel_upper/channel_lower for its earliest
      // bars (IndicatorHistoryPoint's own doc comment) -- those bars must be
      // dropped from the channel series data, not passed through as null
      // (Lightweight Charts throws synchronously on a non-numeric point).
      mockHistory(twoBars)
      mockIndicators({
        ticker: 'AAPL',
        points: [
          { ...indicatorPoints.points[0], channel_upper: null, channel_lower: null },
          indicatorPoints.points[1],
        ],
      })

      renderWithProviders(<PriceChart ticker="AAPL" />)

      await waitFor(() => expect(createSeriesMarkersMock).toHaveBeenCalledTimes(1))

      expect(setDataMock).toHaveBeenCalledWith([{ time: '2026-09-02', value: 233.3 }])
      expect(setDataMock).toHaveBeenCalledWith([{ time: '2026-09-02', value: 219.5 }])
    })

    it('shows the Channel and Value Zone legend with MetricHelp affordances once the overlay resolves', async () => {
      mockHistory(twoBars)

      renderWithProviders(<PriceChart ticker="AAPL" />)

      await waitFor(() => expect(createSeriesMarkersMock).toHaveBeenCalledTimes(1))

      expect(screen.getByText('Channel (Autoenvelope)')).toBeInTheDocument()
      expect(screen.getByText('Value Zone (EMA 13-26)')).toBeInTheDocument()
      expect(
        screen.getByRole('button', { name: 'Channel (Autoenvelope) help' }),
      ).toBeInTheDocument()
      expect(
        screen.getByRole('button', { name: 'Value Zone (EMA 13-26) help' }),
      ).toBeInTheDocument()
    })

    it("opens the Channel MetricHelp balloon with the current channel bounds and the latest close's position within them", async () => {
      mockHistory(twoBars)
      const user = userEvent.setup()

      renderWithProviders(<PriceChart ticker="AAPL" />)

      await waitFor(() => expect(createSeriesMarkersMock).toHaveBeenCalledTimes(1))

      await user.click(
        screen.getByRole('button', { name: 'Channel (Autoenvelope) help' }),
      )

      // Latest indicator point (09-02): channel_upper 233.3, channel_lower
      // 219.5. Latest close (from twoBars, 09-02): 229.7 -- inside the band.
      expect(screen.getByText(/219\.50-233\.30/)).toBeInTheDocument()
      expect(screen.getByText(/229\.70/)).toBeInTheDocument()
      expect(screen.getByText(/inside the channel/)).toBeInTheDocument()
    })

    it('opens the Value Zone MetricHelp balloon with the current EMA13-EMA26 bounds', async () => {
      mockHistory(twoBars)
      const user = userEvent.setup()

      renderWithProviders(<PriceChart ticker="AAPL" />)

      await waitFor(() => expect(createSeriesMarkersMock).toHaveBeenCalledTimes(1))

      await user.click(
        screen.getByRole('button', { name: 'Value Zone (EMA 13-26) help' }),
      )

      // Latest indicator point (09-02): ema_13 226.4, ema_26 221.7.
      expect(screen.getByText(/221\.70-226\.40/)).toBeInTheDocument()
    })

    it('reorders the candlestick series above every fill series (value-zone mask + support/resistance zone bands) so neither ever occludes a candle (PR #151 regression, extended by frontend-support-resistance-overlay)', async () => {
      // Regression test for the blocking pr-reviewer finding on PR #151:
      // Lightweight Charts draws later-added series above earlier ones on
      // the same pane, and the two value-zone `AreaSeries` (one an opaque
      // `theme.palette.background.paper` mask) used to be added *after* the
      // candlestick series, painting over any candle that dipped below the
      // zone. The original fix called a hardcoded `series.setSeriesOrder(2)`
      // once both zone series existed -- frontend-support-resistance-overlay
      // replaced that with `bringSeriesToFront` (utils/chart.ts), a dynamic
      // "move to the end of this pane's series list" call, since a second
      // effect (support/resistance zone bands, below) now also adds its own
      // fill series to the same pane: a hardcoded index from one effect
      // would go stale the moment the *other* effect's own fill-adding
      // logic changes how many series exist in the pane by the time it
      // runs. Both effects end by calling `bringSeriesToFront`, so whichever
      // runs last always leaves the candlestick series painting on top of
      // everything -- this asserts against the dynamically-computed final
      // series count (not a hardcoded literal), which is what actually
      // exercises that self-healing behavior rather than just re-asserting
      // the original fix's own specific number.
      mockHistory(twoBars)

      renderWithProviders(<PriceChart ticker="AAPL" />)

      await waitFor(() => expect(createSeriesMarkersMock).toHaveBeenCalledTimes(1))
      // The default /analysis MSW fixture's one support/resistance zone
      // adds an 8th series (see the "overlays EMA13/EMA26..." test above);
      // wait for it so both fill-adding effects have finished reordering.
      await waitFor(() => expect(addSeriesMock).toHaveBeenCalledTimes(8))

      expect(setSeriesOrderMock).toHaveBeenCalledTimes(2)
      // Value-zone effect's own reorder call: candlestick(1) + the two
      // value-zone AreaSeries(2) = 3 series in the pane at that point, so
      // index 2 (0-based, last).
      expect(setSeriesOrderMock).toHaveBeenNthCalledWith(1, 2)
      // Zones effect's own reorder call, run after all 8 series exist.
      expect(setSeriesOrderMock).toHaveBeenNthCalledWith(2, 7)
    })

    it('does not show the channel/value-zone legend while the overlay has not resolved', async () => {
      mockHistory(twoBars)
      mockIndicators({ ticker: 'AAPL', points: [] })

      renderWithProviders(<PriceChart ticker="AAPL" />)

      await waitFor(() =>
        expect(
          screen.getByText('No signal history available for AAPL.'),
        ).toBeInTheDocument(),
      )
      expect(screen.queryByText('Channel (Autoenvelope)')).not.toBeInTheDocument()
      expect(screen.queryByText('Value Zone (EMA 13-26)')).not.toBeInTheDocument()
    })
  })

  describe('support/resistance zones (frontend-support-resistance-overlay)', () => {
    it('draws a BaselineSeries band per zone spanning the full visible bar range, colored by role and bounded by [lower, upper]', async () => {
      mockHistory(twoBars)
      mockAnalysis([
        buildZone({ role: 'resistance', upper: 236.9, lower: 233.4, strength_score: 80 }),
        buildZone({ role: 'support', upper: 225.0, lower: 222.0, strength_score: 20 }),
      ])

      renderWithProviders(<PriceChart ticker="AAPL" />)

      await waitFor(() => expect(addSeriesMock).toHaveBeenCalledTimes(9))

      // Each zone's BaselineSeries plots a flat line at `upper`, spanning
      // the first and last visible bar (not the zone's own
      // first_touch_date/last_touch_date) -- a support/resistance level is
      // a live reference price today, not scoped to when it was touched.
      expect(setDataMock).toHaveBeenCalledWith([
        { time: '2026-09-01', value: 236.9 },
        { time: '2026-09-02', value: 236.9 },
      ])
      expect(setDataMock).toHaveBeenCalledWith([
        { time: '2026-09-01', value: 225.0 },
        { time: '2026-09-02', value: 225.0 },
      ])

      const baselineCalls = addSeriesMock.mock.calls.filter(
        ([definition]) => definition === 'BaselineSeries-definition',
      )
      expect(baselineCalls).toHaveLength(2)
      const [resistanceOptions, supportOptions] = baselineCalls.map(
        ([, options]) => options,
      ) as [
        { baseValue: { price: number }; title: string },
        { baseValue: { price: number }; title: string },
      ]
      expect(resistanceOptions.baseValue).toEqual({ type: 'price', price: 233.4 })
      expect(resistanceOptions.title).toBe('Resistance zone')
      expect(supportOptions.baseValue).toEqual({ type: 'price', price: 222.0 })
      expect(supportOptions.title).toBe('Support zone')
    })

    it("shades a zone's fill more strongly the higher its strength_score", async () => {
      mockHistory(twoBars)
      mockAnalysis([
        buildZone({ strength_score: 0 }),
        buildZone({ strength_score: 100, upper: 210.0, lower: 205.0 }),
      ])

      renderWithProviders(<PriceChart ticker="AAPL" />)

      await waitFor(() => expect(addSeriesMock).toHaveBeenCalledTimes(9))

      const baselineCalls = addSeriesMock.mock.calls.filter(
        ([definition]) => definition === 'BaselineSeries-definition',
      )
      const [weakOptions, strongOptions] = baselineCalls.map(
        ([, options]) => options as { topFillColor1: string },
      )
      // Both share the same base color (role never changed between the two
      // zones here), but the alpha (opacity) suffix must differ -- a
      // strength_score of 100 reads as more visually prominent than 0.
      expect(weakOptions.topFillColor1).not.toBe(strongOptions.topFillColor1)
      expect(weakOptions.topFillColor1.slice(0, 7)).toBe(
        strongOptions.topFillColor1.slice(0, 7),
      )
    })

    it('draws a broken (role-flipped) zone dashed, distinct from an unbroken zone drawn solid', async () => {
      mockHistory(twoBars)
      mockAnalysis([
        buildZone({ broken: false, upper: 236.9, lower: 233.4 }),
        buildZone({ broken: true, upper: 210.0, lower: 205.0, break_date: '2026-08-01' }),
      ])

      renderWithProviders(<PriceChart ticker="AAPL" />)

      await waitFor(() => expect(addSeriesMock).toHaveBeenCalledTimes(9))

      const baselineCalls = addSeriesMock.mock.calls.filter(
        ([definition]) => definition === 'BaselineSeries-definition',
      )
      const [unbrokenOptions, brokenOptions] = baselineCalls.map(
        ([, options]) => options as { lineStyle: number },
      )
      expect(unbrokenOptions.lineStyle).toBe(0) // LineStyle.Solid
      expect(brokenOptions.lineStyle).toBe(2) // LineStyle.Dashed
    })

    it('caps rendered zones at the strongest 6, even when more are returned', async () => {
      mockHistory(twoBars)
      mockAnalysis(
        Array.from({ length: 9 }, (_, index) =>
          buildZone({
            upper: 200 + index,
            lower: 195 + index,
            strength_score: 90 - index,
          }),
        ),
      )

      renderWithProviders(<PriceChart ticker="AAPL" />)

      // Candlestick + value-zone (2) + EMA13/EMA26 (2) + channel (2) + 6
      // (capped) zone bands = 13.
      await waitFor(() => expect(addSeriesMock).toHaveBeenCalledTimes(13))
      const baselineCalls = addSeriesMock.mock.calls.filter(
        ([definition]) => definition === 'BaselineSeries-definition',
      )
      expect(baselineCalls).toHaveLength(6)
    })

    it('marks a false breakout distinctly and places a dashed stop price line at its extreme_price', async () => {
      mockHistory(twoBars)
      mockAnalysis([
        buildZone({
          role: 'resistance',
          false_breakout: {
            direction: 'up',
            breakout_date: '2026-08-20',
            reentry_date: '2026-09-02',
            extreme_price: 238.5,
          },
        }),
      ])

      renderWithProviders(<PriceChart ticker="AAPL" />)

      await waitFor(() => expect(createSeriesMarkersMock).toHaveBeenCalledTimes(2))

      // Call 0 is the BUY/SELL signal-overlay markers plugin (see the
      // "signal overlay" describe block above); call 1 is this zone's own
      // false-breakout marker.
      const [, falseBreakoutMarkers] = createSeriesMarkersMock.mock.calls[1] as [
        unknown,
        unknown[],
      ]
      expect(falseBreakoutMarkers).toHaveLength(1)
      expect(falseBreakoutMarkers[0]).toMatchObject({
        time: '2026-09-02',
        position: 'aboveBar',
        shape: 'arrowDown',
        text: 'False breakout',
      })

      await waitFor(() => expect(createPriceLineMock).toHaveBeenCalledTimes(1))
      expect(createPriceLineMock).toHaveBeenCalledWith(
        expect.objectContaining({ price: 238.5, title: 'False-breakout stop' }),
      )
    })

    it('omits a false-breakout marker/price line whose reentry_date falls outside the currently visible bar range', async () => {
      mockHistory(twoBars)
      mockAnalysis([
        buildZone({
          false_breakout: {
            direction: 'down',
            breakout_date: '2025-01-01',
            reentry_date: '2025-01-15',
            extreme_price: 200.0,
          },
        }),
      ])

      renderWithProviders(<PriceChart ticker="AAPL" />)

      // One zone still renders its band regardless (candlestick + value-zone
      // (2) + EMA13/EMA26 (2) + channel (2) + 1 zone band = 8) -- only the
      // false-breakout marker/price line are windowed out.
      await waitFor(() => expect(addSeriesMock).toHaveBeenCalledTimes(8))

      // Only the signal-overlay's own BUY/SELL markers plugin runs -- no
      // second createSeriesMarkers call for a false breakout whose
      // reentry_date (2025-01-15) predates every visible bar.
      expect(createSeriesMarkersMock).toHaveBeenCalledTimes(1)
      expect(createPriceLineMock).not.toHaveBeenCalled()
    })

    it('renders zone bands regardless of interval, unlike the daily-only EMA/signal overlay', async () => {
      server.use(
        http.get('/api/stocks/:ticker/history', ({ request }) => {
          const interval = new URL(request.url).searchParams.get('interval')
          return HttpResponse.json({
            ...twoBars,
            interval: (interval ?? 'daily') as 'daily' | 'weekly',
          })
        }),
      )
      mockAnalysis([buildZone()])
      const user = userEvent.setup()

      renderWithProviders(<PriceChart ticker="AAPL" />)

      await waitFor(() =>
        expect(screen.getByTestId('price-chart-canvas')).toBeInTheDocument(),
      )
      // Daily: candlestick + zone band = 2 (the EMA/signal overlay is
      // disabled by `mockIndicators` never resolving for a weekly-only
      // test double -- irrelevant here since `indicators` still resolves
      // via the default `mockIndicators(indicatorPoints)` from
      // `beforeEach`, so the full 8-series daily set renders first).
      await waitFor(() => expect(addSeriesMock).toHaveBeenCalledTimes(8))

      addSeriesMock.mockClear()
      const intervalGroup = screen.getByRole('group', { name: 'Price history interval' })
      await user.click(within(intervalGroup).getByRole('button', { name: 'Weekly' }))

      await waitFor(() =>
        expect(screen.getByTestId('price-chart-canvas')).toBeInTheDocument(),
      )
      // Weekly: the EMA/signal/channel/value-zone overlay is disabled
      // (`overlayEnabled` is false), but the zone band still renders --
      // candlestick + 1 zone BaselineSeries = 2 total.
      await waitFor(() => expect(addSeriesMock).toHaveBeenCalledTimes(2))
      expect(
        addSeriesMock.mock.calls.some(
          ([definition]) => definition === 'BaselineSeries-definition',
        ),
      ).toBe(true)
    })

    it('shows the Support/Resistance Zones and False Breakout legend with MetricHelp affordances', async () => {
      mockHistory(twoBars)
      mockAnalysis([
        buildZone({ role: 'resistance', upper: 231.0, lower: 229.9, broken: false }),
        buildZone({
          role: 'support',
          upper: 210.0,
          lower: 205.0,
          false_breakout: {
            direction: 'down',
            breakout_date: '2026-08-20',
            reentry_date: '2026-09-02',
            extreme_price: 203.5,
          },
        }),
      ])

      renderWithProviders(<PriceChart ticker="AAPL" />)

      await waitFor(() =>
        expect(screen.getByText('Support/Resistance Zones')).toBeInTheDocument(),
      )
      expect(screen.getByText('False Breakout')).toBeInTheDocument()
      expect(
        screen.getByRole('button', { name: 'Support/Resistance Zones help' }),
      ).toBeInTheDocument()
      expect(
        screen.getByRole('button', { name: 'False Breakout help' }),
      ).toBeInTheDocument()
    })

    it('opens the Support/Resistance Zones MetricHelp balloon with the zone nearest the latest close', async () => {
      mockHistory(twoBars)
      mockAnalysis([
        buildZone({ role: 'resistance', upper: 231.0, lower: 229.9, broken: false }),
        buildZone({ role: 'support', upper: 210.0, lower: 205.0 }),
      ])
      const user = userEvent.setup()

      renderWithProviders(<PriceChart ticker="AAPL" />)

      await waitFor(() =>
        expect(screen.getByText('Support/Resistance Zones')).toBeInTheDocument(),
      )
      await user.click(
        screen.getByRole('button', { name: 'Support/Resistance Zones help' }),
      )
      // Latest close (twoBars, 09-02): 229.7 -- nearest to the resistance
      // zone (229.9-231.0), not the support zone far below it.
      expect(screen.getByText(/Showing 2 of 2 detected zones/)).toBeInTheDocument()
      expect(screen.getByText(/Resistance 229\.90-231\.00/)).toBeInTheDocument()
    })

    it("opens the False Breakout MetricHelp balloon with the most recent breakout's direction, zone, and suggested stop", async () => {
      mockHistory(twoBars)
      mockAnalysis([
        buildZone({ role: 'resistance', upper: 231.0, lower: 229.9 }),
        buildZone({
          role: 'support',
          upper: 210.0,
          lower: 205.0,
          false_breakout: {
            direction: 'down',
            breakout_date: '2026-08-20',
            reentry_date: '2026-09-02',
            extreme_price: 203.5,
          },
        }),
      ])
      const user = userEvent.setup()

      renderWithProviders(<PriceChart ticker="AAPL" />)

      await waitFor(() => expect(screen.getByText('False Breakout')).toBeInTheDocument())
      await user.click(screen.getByRole('button', { name: 'False Breakout help' }))
      expect(
        screen.getByText(/support zone 205\.00-210\.00 broke below it/),
      ).toBeInTheDocument()
      expect(screen.getByText(/stop near 203\.50/)).toBeInTheDocument()
    })

    it('does not show the support/resistance legend when no zones are detected', async () => {
      mockHistory(twoBars)
      mockAnalysis([])

      renderWithProviders(<PriceChart ticker="AAPL" />)

      await waitFor(() =>
        expect(screen.getByTestId('price-chart-canvas')).toBeInTheDocument(),
      )
      await waitFor(() => expect(createSeriesMarkersMock).toHaveBeenCalledTimes(1))
      expect(screen.queryByText('Support/Resistance Zones')).not.toBeInTheDocument()
      expect(screen.queryByText('False Breakout')).not.toBeInTheDocument()
    })

    it('swaps the zone band/marker/price-line series in place (without recreating the candlestick chart) when only the analysis query refetches', async () => {
      // Same rationale as the signal-overlay describe block's own "swaps...
      // in place" test above: an `/analysis`-only refetch leaves
      // `historyQuery.data` referentially unchanged, so the candlestick
      // effect never re-runs and `chartRef`/`seriesRef` keep pointing at
      // the same chart -- this is the path where THIS effect's own cleanup
      // guard sees matching refs and actually calls `chart.removeSeries(...)`/
      // `series.removePriceLine(...)`/the false-breakout markers plugin's
      // `detach()` for real (as opposed to skipping because the candlestick
      // effect already tore the chart down first).
      mockHistory(twoBars)
      mockAnalysis([
        buildZone({
          false_breakout: {
            direction: 'up',
            breakout_date: '2026-08-20',
            reentry_date: '2026-09-02',
            extreme_price: 238.5,
          },
        }),
      ])
      const queryClient = createTestQueryClient()

      renderWithProviders(<PriceChart ticker="AAPL" />, { queryClient })

      await waitFor(() => expect(createPriceLineMock).toHaveBeenCalledTimes(1))
      expect(createChartMock).toHaveBeenCalledTimes(1)

      mockAnalysis([buildZone({ upper: 210.0, lower: 205.0 })])
      await queryClient.invalidateQueries({
        queryKey: stocksKeys.analysis('AAPL'),
      })

      await waitFor(() =>
        expect(setDataMock).toHaveBeenCalledWith([
          { time: '2026-09-01', value: 210.0 },
          { time: '2026-09-02', value: 210.0 },
        ]),
      )

      // The candlestick chart itself was never recreated...
      expect(createChartMock).toHaveBeenCalledTimes(1)
      expect(removeMock).not.toHaveBeenCalled()
      // ...but the stale zone band series, false-breakout price line, and
      // false-breakout markers plugin were removed/detached for real before
      // the new ones were added (the new zone has no false breakout, so no
      // second `createPriceLine` call follows).
      expect(removeSeriesMock).toHaveBeenCalledTimes(1)
      expect(removePriceLineMock).toHaveBeenCalledTimes(1)
      expect(detachMarkersMock).toHaveBeenCalledTimes(1)
      expect(createPriceLineMock).toHaveBeenCalledTimes(1)
    })
  })
})
