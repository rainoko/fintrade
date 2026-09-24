import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type {
  AnalysisResponse,
  DivergenceOut,
  HistoryResponse,
  IndicatorHistoryResponse,
  KangarooTailOut,
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
  // `series.priceScale()` (frontend-tide-region-chart-shading) -- see
  // `priceScaleApplyOptionsMock`'s own comment above for why this is a
  // per-series method here, not `chart.priceScale(id)`.
  priceScale: () => ({
    applyOptions: (options: unknown) => priceScaleApplyOptionsMock(options),
  }),
}))
const setMarkersMock = vi.fn()
const detachMarkersMock = vi.fn()
const createSeriesMarkersMock = vi.fn((_series: unknown, markers: unknown) => {
  setMarkersMock(markers)
  return { setMarkers: setMarkersMock, markers: () => markers, detach: detachMarkersMock }
})
// Divergence-marker click-to-explain (frontend-divergence-markers):
// `subscribeClick`/`unsubscribeClick` mocks so tests can capture the
// handler `PriceChart.tsx`'s divergence-overlay effect registers and
// invoke it directly with a synthetic `MouseEventParams`-shaped object,
// simulating a click on a divergence marker (jsdom has no real canvas for
// an actual pointer event to hit-test against — same reasoning this file's
// own top comment already gives for mocking the whole module).
const subscribeClickMock = vi.fn()
const unsubscribeClickMock = vi.fn()
// Tide background shading (frontend-tide-region-chart-shading) configures
// its own dedicated, invisible price scale via
// `series.priceScale().applyOptions(...)` (called on one of the three
// region series themselves, NOT `chart.priceScale(id)` -- the real
// Lightweight Charts library throws synchronously on that for an ID no
// series has referenced yet, a real bug a live browser walkthrough caught
// that this mock's own earlier, more permissive shape did not; see
// PriceChart.tsx's own comment at the call site). `priceScaleApplyOptionsMock`
// tracks that configuration call so tests can assert it (invisible, zero
// margins) the same way `setSeriesOrderMock` tracks `bringSeriesToFront`'s
// calls.
const priceScaleApplyOptionsMock = vi.fn()
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
    subscribeClick: (handler: unknown) => subscribeClickMock(handler),
    unsubscribeClick: (handler: unknown) => unsubscribeClickMock(handler),
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
  LineStyle: { Solid: 0, Dotted: 1, Dashed: 2, LargeDashed: 3 },
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
  trading_mode: { mode: 'swing', day_trader_timeframe_triple: null },
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
  divergence: null,
  kangaroo_tail: null,
  indicators: {
    ema_13: 226.4,
    ema_26: 221.7,
    macd_histogram: 1.82,
    bull_power: 3.1,
    bear_power: -1.4,
    trend_strength: { atr: 4.2, plus_di: 28.5, minus_di: 15.3, adx: 22.1 },
  },
  support_resistance_zones: [],
  extended_data: {
    earnings_date: null,
    earnings_within_warning_days: false,
    ex_dividend_date: null,
    shares_short: null,
    short_ratio: null,
    short_percent_of_float: null,
    float_shares: null,
    insider_transactions: [],
    unavailable_reason: null,
  },
  insider_clusters: [],
}

function mockAnalysis(
  zones: SupportResistanceZone[],
  overrides: Partial<AnalysisResponse> = {},
) {
  server.use(
    http.get('/api/stocks/:ticker/analysis', () =>
      HttpResponse.json({ ...baseAnalysis, support_resistance_zones: zones, ...overrides }),
    ),
  )
}

// A hand-computed bullish MACD-Histogram divergence fixture (frontend-
// divergence-markers): two price swing lows 20 trading days apart (Kerry
// Lovvorn's own spacing minimum), the second shallower on MACD-Histogram
// than the first (-1.5 vs -6.0, well under half-depth), with the
// centerline crossed between them and not yet aborted -- a plausible,
// fully-schema-valid `DivergenceOut` value, not asserting anything about
// how the backend itself would have computed it (that's
// backend-divergence-detection's own hand-verified reference tests).
const bullishDivergence: DivergenceOut = {
  indicator: 'macd_histogram',
  kind: 'bullish',
  first_extreme_date: '2026-08-03',
  first_extreme_price: 210.5,
  first_extreme_indicator_value: -6.0,
  second_extreme_date: '2026-08-31',
  second_extreme_price: 205.2,
  second_extreme_indicator_value: -1.5,
  bars_apart: 20,
  centerline_crossed: true,
  beyond_reference_line: null,
  aborted: false,
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
      tide: { trend: 'NEUTRAL', weekly_macd_histogram_slope: 'flat' },
      ema_13: 225.1,
      ema_26: 220.4,
      macd_histogram: 1.2,
      bull_power: 2.5,
      bear_power: -1.1,
      stochastic_k: 55.0,
      force_index_2ema: 1000.0,
      obv: 12000.0,
      accumulation_distribution: 3400.0,
      channel_upper: 232.0,
      channel_lower: 218.2,
      trend_strength: { atr: 3.8, plus_di: 26.0, minus_di: 18.5, adx: 20.0 },
      signal: 'HOLD',
      confidence: 0,
      confidence_band: 'Low',
    },
    {
      date: '2026-09-02',
      tide: { trend: 'NEUTRAL', weekly_macd_histogram_slope: 'flat' },
      ema_13: 226.4,
      ema_26: 221.7,
      macd_histogram: 1.82,
      bull_power: 3.1,
      bear_power: -1.4,
      stochastic_k: 24.3,
      force_index_2ema: -18234.5,
      obv: 10500.0,
      accumulation_distribution: 2900.0,
      channel_upper: 233.3,
      channel_lower: 219.5,
      trend_strength: { atr: 4.2, plus_di: 28.5, minus_di: 15.3, adx: 22.1 },
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

// Post-review fix (PR #158, blocking finding): the divergence overlay is
// now windowed to the currently visible bar range (see
// `divergenceClick.ts#isDivergenceInRange`), so a test exercising the
// overlay actually being drawn needs bars spanning `bullishDivergence`'s own
// two extreme dates (2026-08-03 / 2026-08-31), unlike `twoBars` above (which
// only covers 2026-09-01/02 and is now deliberately reused by the new
// "out of range" tests below to exercise the windowing itself).
const barsSpanningDivergence: HistoryResponse = {
  ticker: 'AAPL',
  interval: 'daily',
  bars: [
    { date: '2026-08-03', open: 212.0, high: 213.0, low: 209.8, close: 210.5, volume: 40123000 },
    { date: '2026-08-31', open: 207.0, high: 208.0, low: 204.6, close: 205.2, volume: 42456000 },
    ...twoBars.bars,
  ],
}

// A plausible, hand-computed bearish (upward-pointing) Kangaroo Tail
// fixture (frontend-kangaroo-tail-markers): suggested_stop is the bar's own
// high-low midpoint, (233.0 + 220.66) / 2 = 226.83, matching the backend's
// own `suggested_stop` formula (see the backend-kangaroo-tail-pattern
// task's decisions) -- not asserting anything about how the backend itself
// would compute it, just a schema-valid fixture with internally-consistent
// numbers.
const upwardKangarooTail: KangarooTailOut = {
  direction: 'up',
  tail_date: '2026-08-15',
  confirmed_date: '2026-08-16',
  high: 233.0,
  low: 220.66,
  range_multiple: 2.8,
  suggested_stop: 226.83,
}

// Bars spanning `upwardKangarooTail`'s own `tail_date` (2026-08-15) --
// same "windowing needs bars covering the fixture's own date" rationale as
// `barsSpanningDivergence` above. The 2026-08-15 bar's own open/close
// (228.0/222.5) is what `kangarooTailHelp.interpretValue`'s legend reads
// via `PriceChart.tsx`'s `kangarooTailBar` lookup.
const barsSpanningKangarooTail: HistoryResponse = {
  ticker: 'AAPL',
  interval: 'daily',
  bars: [
    { date: '2026-08-15', open: 228.0, high: 233.0, low: 220.66, close: 222.5, volume: 40000000 },
    ...twoBars.bars,
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
    priceScaleApplyOptionsMock.mockClear()
    setMarkersMock.mockClear()
    detachMarkersMock.mockClear()
    createSeriesMarkersMock.mockClear()
    createPriceLineMock.mockClear()
    removePriceLineMock.mockClear()
    subscribeClickMock.mockClear()
    unsubscribeClickMock.mockClear()
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
      // (channel upper/lower LineSeries) + (1 tide-region AreaSeries,
      // frontend-tide-region-chart-shading -- both of `indicatorPoints`'
      // fixture points share the same Neutral trend, so this is a single
      // contiguous segment, not 3) + (1 support/resistance zone
      // BaselineSeries, from the default MSW /analysis fixture's single
      // zone) = 9 addSeries calls once every overlay resolves; each fed its
      // own values straight from the backend response — no client-side
      // indicator math.
      await waitFor(() => expect(addSeriesMock).toHaveBeenCalledTimes(9))
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
      // AreaSeries, EMA13/EMA26, and channel upper/lower LineSeries (6),
      // plus the 1 tide-region AreaSeries (frontend-tide-region-chart-
      // shading, which shares this exact same `indicatorsQuery.data`
      // dependency -- `indicatorPoints`' fixture is a single Neutral
      // segment, so just 1 series) -- 7 series total (minus the one
      // candlestick series, which isn't touched by this cleanup at all).
      // The support/resistance zone BaselineSeries from the default
      // /analysis fixture is untouched by this refetch too -- its own
      // effect depends on `analysisQuery.data`, not `indicatorsQuery.data`,
      // so it never re-runs/cleans up here.
      expect(removeSeriesMock).toHaveBeenCalledTimes(7)
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

    it('reorders the candlestick series above every fill series (value-zone mask + tide-region shading + support/resistance zone bands) so neither ever occludes a candle (PR #151 regression, extended by frontend-support-resistance-overlay and frontend-tide-region-chart-shading)', async () => {
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
      // runs. A THIRD effect now also adds fill series to this same pane
      // (one tide-region `AreaSeries` per contiguous segment,
      // frontend-tide-region-chart-shading -- `indicatorPoints`' fixture is
      // a single Neutral segment, so just 1 series here) -- all three
      // effects end by calling `bringSeriesToFront`, so whichever runs last
      // always leaves the candlestick series painting on top of everything
      // -- this asserts against the dynamically-computed final series count
      // (not a hardcoded literal), which is what actually exercises that
      // self-healing behavior rather than just re-asserting the original
      // fix's own specific number.
      mockHistory(twoBars)

      renderWithProviders(<PriceChart ticker="AAPL" />)

      await waitFor(() => expect(createSeriesMarkersMock).toHaveBeenCalledTimes(1))
      // The default /analysis MSW fixture's one support/resistance zone
      // adds the 9th series (see the "overlays EMA13/EMA26..." test above);
      // wait for it so all three fill-adding effects have finished
      // reordering.
      await waitFor(() => expect(addSeriesMock).toHaveBeenCalledTimes(9))

      expect(setSeriesOrderMock).toHaveBeenCalledTimes(3)
      // Value-zone effect's own reorder call (called mid-effect, right
      // after just its own two AreaSeries, before the EMA/channel
      // LineSeries are added -- see the effect's own doc comment):
      // candlestick(1) + the two value-zone AreaSeries(2) = 3 series in the
      // pane at that point, so index 2 (0-based, last).
      expect(setSeriesOrderMock).toHaveBeenNthCalledWith(1, 2)
      // Tide-region effect's own reorder call, run after the value-zone
      // effect has finished adding all 6 of its own series (2 AreaSeries +
      // EMA13/EMA26 + channel upper/lower) plus this effect's own 1
      // AreaSeries: candlestick(1) + 6 + 1 = 8 series, so index 7.
      expect(setSeriesOrderMock).toHaveBeenNthCalledWith(2, 7)
      // Zones effect's own reorder call, run after all 9 series exist.
      expect(setSeriesOrderMock).toHaveBeenNthCalledWith(3, 8)
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

  describe('tide background shading (frontend-tide-region-chart-shading)', () => {
    // Four bars spanning a Bullish stretch (08-28/08-31), one Neutral bar
    // (09-01), then a Bearish bar (09-02) -- enough to exercise every
    // trend's own region array and a transition between all three, unlike
    // `indicatorPoints` (both points Neutral) used by every other test in
    // this file.
    const mixedTideBars: HistoryResponse = {
      ticker: 'AAPL',
      interval: 'daily',
      bars: [
        { date: '2026-08-28', open: 220.0, high: 222.0, low: 219.0, close: 221.0, volume: 40000000 },
        { date: '2026-08-31', open: 221.0, high: 223.0, low: 220.0, close: 222.5, volume: 41000000 },
        ...twoBars.bars,
      ],
    }
    const mixedTideIndicators: IndicatorHistoryResponse = {
      ticker: 'AAPL',
      points: [
        {
          ...indicatorPoints.points[0],
          date: '2026-08-28',
          tide: { trend: 'BULLISH', weekly_macd_histogram_slope: 'rising' },
        },
        {
          ...indicatorPoints.points[0],
          date: '2026-08-31',
          tide: { trend: 'BULLISH', weekly_macd_histogram_slope: 'rising' },
        },
        {
          ...indicatorPoints.points[0],
          date: '2026-09-01',
          tide: { trend: 'NEUTRAL', weekly_macd_histogram_slope: 'flat' },
        },
        {
          ...indicatorPoints.points[1],
          date: '2026-09-02',
          tide: { trend: 'BEARISH', weekly_macd_histogram_slope: 'falling' },
        },
      ],
    }

    it('draws one AreaSeries per contiguous same-trend segment on a dedicated invisible price scale, each series holding only its own segment\'s bars', async () => {
      mockHistory(mixedTideBars)
      mockIndicators(mixedTideIndicators)

      renderWithProviders(<PriceChart ticker="AAPL" />)

      await waitFor(() => expect(createSeriesMarkersMock).toHaveBeenCalledTimes(1))

      const tideRegionCalls = addSeriesMock.mock.calls.filter(
        ([, options]) =>
          (options as { priceScaleId?: string } | undefined)?.priceScaleId ===
          'tide-region-shading',
      )
      // 3 contiguous segments: Bullish (08-28, 08-31), Neutral (09-01),
      // Bearish (09-02) -- one AreaSeries per segment, not one per trend
      // (see `buildTideRegionSegments`'s own doc comment for why "one per
      // trend" renders wrong: `AreaSeries` bridges its fill straight across
      // any gap, real or explicit whitespace, between two of that series'
      // own real points).
      expect(tideRegionCalls).toHaveLength(3)

      // Post-review fix (PR #169 needs_work): each segment's own series
      // holds only its own bars, PLUS one boundary point shared with
      // whichever adjacent segment doesn't already own that boundary --
      // Bullish gets no boundary point of its own here because the
      // trailing one it would otherwise have gained (into Neutral's own
      // 09-01) was reclaimed by the backward cascade fix so the solo
      // Neutral segment could use it as ITS OWN leading point instead, and
      // that same reclaim-and-hand-down cascade repeats one more time so
      // the solo (and, pre-fix, entirely unshaded) trailing Bearish segment
      // also ends up a real 2-point span rather than a lone, unrenderable
      // point. See `buildTideRegionSegments`'s own doc comment for the full
      // reasoning and the one pathological case (every bar alternating
      // trend) this cascade can't fix.
      expect(setDataMock).toHaveBeenCalledWith([
        { time: '2026-08-28', value: 1 },
        { time: '2026-08-31', value: 1 },
      ])
      expect(setDataMock).toHaveBeenCalledWith([
        { time: '2026-08-31', value: 1 },
        { time: '2026-09-01', value: 1 },
      ])
      expect(setDataMock).toHaveBeenCalledWith([
        { time: '2026-09-01', value: 1 },
        { time: '2026-09-02', value: 1 },
      ])

      // The dedicated price scale is configured invisible with zero
      // margins, so its [0, 1] range maps exactly onto the pane's own
      // pixel top/bottom -- see `TIDE_REGION_PRICE_SCALE_ID`'s own comment
      // in PriceChart.tsx for why. Configured via one of the region
      // series' own `.priceScale()`, not `chart.priceScale(id)` -- see
      // this task's `decisions` entry for why.
      expect(priceScaleApplyOptionsMock).toHaveBeenCalledWith({
        visible: false,
        scaleMargins: { top: 0, bottom: 0 },
      })
    })

    it('gives a solo trailing (most-recent-bar) segment a real two-point span instead of a lone, unrenderable point (PR #169 needs_work fix)', async () => {
      // Three Bullish bars, then a single Bearish bar as the most recent
      // (rightmost) one -- the exact scenario the review comment flagged:
      // only the LAST segment is solo (unlike `mixedTideIndicators` above,
      // where the second-to-last segment is ALSO solo and exercises the
      // backward cascade one extra step).
      const soloTrailingBars: HistoryResponse = {
        ticker: 'AAPL',
        interval: 'daily',
        bars: [
          { date: '2026-08-28', open: 220.0, high: 222.0, low: 219.0, close: 221.0, volume: 40000000 },
          { date: '2026-08-31', open: 221.0, high: 223.0, low: 220.0, close: 222.5, volume: 41000000 },
          { date: '2026-09-01', open: 222.5, high: 224.0, low: 221.5, close: 223.5, volume: 42000000 },
          ...twoBars.bars.slice(1),
        ],
      }
      const soloTrailingIndicators: IndicatorHistoryResponse = {
        ticker: 'AAPL',
        points: [
          {
            ...indicatorPoints.points[0],
            date: '2026-08-28',
            tide: { trend: 'BULLISH', weekly_macd_histogram_slope: 'rising' },
          },
          {
            ...indicatorPoints.points[0],
            date: '2026-08-31',
            tide: { trend: 'BULLISH', weekly_macd_histogram_slope: 'rising' },
          },
          {
            ...indicatorPoints.points[0],
            date: '2026-09-01',
            tide: { trend: 'BULLISH', weekly_macd_histogram_slope: 'rising' },
          },
          {
            ...indicatorPoints.points[1],
            date: '2026-09-02',
            tide: { trend: 'BEARISH', weekly_macd_histogram_slope: 'falling' },
          },
        ],
      }
      mockHistory(soloTrailingBars)
      mockIndicators(soloTrailingIndicators)

      renderWithProviders(<PriceChart ticker="AAPL" />)

      await waitFor(() => expect(createSeriesMarkersMock).toHaveBeenCalledTimes(1))

      const tideRegionCalls = addSeriesMock.mock.calls.filter(
        ([, options]) =>
          (options as { priceScaleId?: string } | undefined)?.priceScaleId ===
          'tide-region-shading',
      )
      expect(tideRegionCalls).toHaveLength(2)

      // Bullish keeps its own real bars only -- the trailing boundary point
      // it would otherwise have gained (into Bearish's own 09-02) is
      // reclaimed so the solo Bearish segment can use it as its own leading
      // point instead.
      expect(setDataMock).toHaveBeenCalledWith([
        { time: '2026-08-28', value: 1 },
        { time: '2026-08-31', value: 1 },
        { time: '2026-09-01', value: 1 },
      ])
      // The solo trailing Bearish segment is now a real 2-point span
      // (leading boundary at Bullish's own last real bar, 09-01) instead of
      // the pre-fix lone `[{ time: '2026-09-02', value: 1 }]` that
      // `AreaSeries` rendered as nothing.
      expect(setDataMock).toHaveBeenCalledWith([
        { time: '2026-09-01', value: 1 },
        { time: '2026-09-02', value: 1 },
      ])
    })

    it('excludes every trend region series from autoscale via a fixed [0, 1] autoscaleInfoProvider', async () => {
      mockHistory(mixedTideBars)
      mockIndicators(mixedTideIndicators)

      renderWithProviders(<PriceChart ticker="AAPL" />)

      await waitFor(() => expect(createSeriesMarkersMock).toHaveBeenCalledTimes(1))

      const tideRegionCalls = addSeriesMock.mock.calls.filter(
        ([, options]) =>
          (options as { priceScaleId?: string } | undefined)?.priceScaleId ===
          'tide-region-shading',
      ) as [unknown, { autoscaleInfoProvider: () => { priceRange: unknown } }][]
      expect(tideRegionCalls).toHaveLength(3)
      for (const [, options] of tideRegionCalls) {
        expect(options.autoscaleInfoProvider()).toEqual({
          priceRange: { minValue: 0, maxValue: 1 },
        })
      }
    })

    it('does not draw the tide-region shading while the Weekly interval is selected', async () => {
      mockHistory(mixedTideBars)
      mockIndicators(mixedTideIndicators)

      renderWithProviders(<PriceChart ticker="AAPL" />)

      await waitFor(() => expect(createSeriesMarkersMock).toHaveBeenCalledTimes(1))
      addSeriesMock.mockClear()

      const user = userEvent.setup()
      const intervalGroup = screen.getByRole('group', { name: 'Price history interval' })
      await user.click(within(intervalGroup).getByRole('button', { name: 'Weekly' }))

      await waitFor(() =>
        expect(screen.getByTestId('price-chart-canvas')).toBeInTheDocument(),
      )
      expect(
        addSeriesMock.mock.calls.some(
          ([, options]) =>
            (options as { priceScaleId?: string } | undefined)?.priceScaleId ===
            'tide-region-shading',
        ),
      ).toBe(false)
    })

    it('shows the Tide Background legend with a MetricHelp affordance reporting the Bullish/Bearish/Neutral split of the currently visible bars', async () => {
      mockHistory(mixedTideBars)
      mockIndicators(mixedTideIndicators)
      const user = userEvent.setup()

      renderWithProviders(<PriceChart ticker="AAPL" />)

      await waitFor(() => expect(createSeriesMarkersMock).toHaveBeenCalledTimes(1))

      expect(
        screen.getByText('Tide Background (Bullish / Neutral / Bearish)'),
      ).toBeInTheDocument()

      await user.click(
        screen.getByRole('button', { name: 'Tide Background (Screen 1 history) help' }),
      )

      // 2 of 4 bars Bullish (50%), 1 Neutral (25%), 1 Bearish (25%); the
      // most recent (rightmost) bar, 09-02, is Bearish.
      expect(screen.getByText(/50% Bullish/)).toBeInTheDocument()
      expect(screen.getByText(/25% Bearish/)).toBeInTheDocument()
      expect(screen.getByText(/25% Neutral/)).toBeInTheDocument()
      expect(screen.getByText(/Bearish \(red\)/)).toBeInTheDocument()
    })

    it('removes the previous tide-region series and adds new ones when only the indicators query refetches', async () => {
      mockHistory(mixedTideBars)
      mockIndicators(mixedTideIndicators)
      const queryClient = createTestQueryClient()

      renderWithProviders(<PriceChart ticker="AAPL" />, { queryClient })

      await waitFor(() => expect(createSeriesMarkersMock).toHaveBeenCalledTimes(1))
      removeSeriesMock.mockClear()
      addSeriesMock.mockClear()

      mockIndicators({
        ticker: 'AAPL',
        points: mixedTideIndicators.points.map((point) => ({
          ...point,
          tide: { trend: 'BULLISH' as const, weekly_macd_histogram_slope: 'rising' as const },
        })),
      })
      await queryClient.invalidateQueries({
        queryKey: stocksKeys.indicators('AAPL', '1y'),
      })

      await waitFor(() => expect(createSeriesMarkersMock).toHaveBeenCalledTimes(2))

      // 6 signal-overlay series removed and re-added, plus the 3
      // tide-region series from the initial (3-segment) render -- the
      // refetched data collapses to a single Bullish segment, so only 1
      // new tide-region series gets added back (see below), but all 3 of
      // the ORIGINAL ones are still removed (all sharing
      // `indicatorsQuery.data` as a dependency) -- same count
      // `removeSeriesMock`'s assertion in the signal-overlay describe block
      // above already establishes for this exact refetch path.
      expect(removeSeriesMock).toHaveBeenCalledTimes(9)

      const tideRegionCalls = addSeriesMock.mock.calls.filter(
        ([, options]) =>
          (options as { priceScaleId?: string } | undefined)?.priceScaleId ===
          'tide-region-shading',
      )
      // Every bar is now Bullish -- one single contiguous segment spanning
      // all four bars, so exactly 1 series (not 3).
      expect(tideRegionCalls).toHaveLength(1)
      expect(setDataMock).toHaveBeenCalledWith([
        { time: '2026-08-28', value: 1 },
        { time: '2026-08-31', value: 1 },
        { time: '2026-09-01', value: 1 },
        { time: '2026-09-02', value: 1 },
      ])
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

      await waitFor(() => expect(addSeriesMock).toHaveBeenCalledTimes(10))

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

      await waitFor(() => expect(addSeriesMock).toHaveBeenCalledTimes(10))

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

      await waitFor(() => expect(addSeriesMock).toHaveBeenCalledTimes(10))

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

      // Candlestick + value-zone (2) + EMA13/EMA26 (2) + channel (2) +
      // tide-region shading (1) + 6 (capped) zone bands = 14.
      await waitFor(() => expect(addSeriesMock).toHaveBeenCalledTimes(14))
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
      // (2) + EMA13/EMA26 (2) + channel (2) + tide-region shading (1) + 1
      // zone band = 9) -- only the false-breakout marker/price line are
      // windowed out.
      await waitFor(() => expect(addSeriesMock).toHaveBeenCalledTimes(9))

      // Only the signal-overlay's own BUY/SELL markers plugin runs -- no
      // second createSeriesMarkers call for a false breakout whose
      // reentry_date (2025-01-15) predates every visible bar.
      expect(createSeriesMarkersMock).toHaveBeenCalledTimes(1)
      expect(createPriceLineMock).not.toHaveBeenCalled()
    })

    it("still shows the False Breakout legend (noting it is not in the current range) and caveats the MetricHelp text when the most recent breakout's reentry_date falls outside the currently visible bar range (followup fix, checklist item 1)", async () => {
      // Regression test for this task's checklist item 1: before this fix,
      // falseBreakoutHelp.interpretValue's "Most recent" reading was
      // windowed only by `displayedZones`, not by the currently visible
      // date range the marker/price-line above are both windowed by -- so
      // it could describe a specific breakout (exact dates + stop price)
      // whose marker/price-line wasn't actually on screen, with no caveat.
      const user = userEvent.setup()
      mockHistory(twoBars)
      mockAnalysis([
        buildZone({
          role: 'resistance',
          upper: 236.9,
          lower: 233.4,
          false_breakout: {
            direction: 'up',
            breakout_date: '2025-01-01',
            reentry_date: '2025-01-15',
            extreme_price: 238.5,
          },
        }),
      ])

      renderWithProviders(<PriceChart ticker="AAPL" />)

      await waitFor(() =>
        expect(screen.getByText(/False Breakout/)).toBeInTheDocument(),
      )
      // The legend row stays visible (same posture as the divergence/
      // Kangaroo Tail legends) but is labeled as out of range...
      expect(
        screen.getByText('False Breakout (not in current range)'),
      ).toBeInTheDocument()

      await user.click(screen.getByRole('button', { name: 'False Breakout help' }))

      // ...and the MetricHelp text still names the real episode in full...
      expect(
        screen.getByText(/resistance zone 233\.40-236\.90 broke above it on 2025-01-01/),
      ).toBeInTheDocument()
      expect(screen.getByText(/238\.50/)).toBeInTheDocument()
      // ...plus the out-of-range caveat, matching the divergence/Kangaroo
      // Tail precedent's own wording convention.
      expect(
        screen.getByText(/isn't marked on the chart right now/),
      ).toBeInTheDocument()
      expect(screen.getByText(/2025-01-15/)).toBeInTheDocument()
    })

    it('shows the False Breakout legend with no out-of-range caveat when the most recent breakout is actually drawn on the chart', async () => {
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

      renderWithProviders(<PriceChart ticker="AAPL" />)

      await waitFor(() =>
        expect(screen.getByText(/False Breakout/)).toBeInTheDocument(),
      )
      expect(screen.getByText('False Breakout')).toBeInTheDocument()
      expect(
        screen.queryByText('False Breakout (not in current range)'),
      ).not.toBeInTheDocument()
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
      // `beforeEach`, so the full 9-series daily set (including the 1
      // tide-region shading series -- `indicatorPoints` is a single
      // Neutral segment) renders first).
      await waitFor(() => expect(addSeriesMock).toHaveBeenCalledTimes(9))

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

    it('excludes a zone far from the latest close from both the display cap and the axis (PR #152 blocking finding #1: autoscale distortion)', async () => {
      mockHistory(twoBars)
      mockAnalysis([
        // Latest close (twoBars, 09-02) is 229.7. A pre-split-era zone at
        // ~10x that price (analogous to the real-world NVDA/MSFT/AMD case
        // the reviewer reproduced) must never reach `setData`/autoscale,
        // regardless of how high its own strength_score is.
        buildZone({ upper: 2350.0, lower: 2300.0, strength_score: 100 }),
        buildZone({ upper: 236.9, lower: 233.4, strength_score: 10 }),
      ])

      renderWithProviders(<PriceChart ticker="AAPL" />)

      // Candlestick + value-zone (2) + EMA13/EMA26 (2) + channel (2) +
      // tide-region shading (1) + only the 1 relevant zone band = 9 (not
      // 10 -- the far-away zone is excluded before the display cap, not
      // just visually deprioritized).
      await waitFor(() => expect(addSeriesMock).toHaveBeenCalledTimes(9))

      const baselineCalls = addSeriesMock.mock.calls.filter(
        ([definition]) => definition === 'BaselineSeries-definition',
      )
      expect(baselineCalls).toHaveLength(1)
      expect(setDataMock).not.toHaveBeenCalledWith(
        expect.arrayContaining([expect.objectContaining({ value: 2350.0 })]),
      )
      expect(setDataMock).toHaveBeenCalledWith([
        { time: '2026-09-01', value: 236.9 },
        { time: '2026-09-02', value: 236.9 },
      ])
    })

    it("excludes a zone within the 50% price-ratio window but well outside the currently-visible bars' own price span (followup fix, checklist item 2: bounded axis distortion on a narrow-range view)", async () => {
      // Regression test for this task's checklist item 2: `twoBars`' own
      // visible high/low span is 3.3 (226.8-230.1), a ~1.4%-of-price sliver
      // -- exactly the "narrow-range view" pr-reviewer's retry-round-1
      // stress test reproduced axis distortion against. A zone ~40% above
      // the 229.7 latest close (320-325) sits well inside the old 50%
      // price-ratio-only window (114.85-344.55), but is now excluded by the
      // added visible-span-based window (floored at 10% of price, expanded
      // 2x either way -- see `ZONE_RELEVANCE_VISIBLE_SPAN_MULTIPLE`'s own
      // comment in PriceChart.tsx), so it can no longer stretch the y-axis
      // on this narrow a view.
      mockHistory(twoBars)
      mockAnalysis([
        buildZone({ upper: 325.0, lower: 320.0, strength_score: 100 }),
        buildZone({ upper: 236.9, lower: 233.4, strength_score: 10 }),
      ])

      renderWithProviders(<PriceChart ticker="AAPL" />)

      // Only the 1 zone actually near the visible bars' own price span
      // reaches setData -- candlestick + value-zone (2) + EMA13/EMA26 (2) +
      // channel (2) + tide-region shading (1) + 1 zone band = 9 (not 10).
      await waitFor(() => expect(addSeriesMock).toHaveBeenCalledTimes(9))

      const baselineCalls = addSeriesMock.mock.calls.filter(
        ([definition]) => definition === 'BaselineSeries-definition',
      )
      expect(baselineCalls).toHaveLength(1)
      expect(setDataMock).not.toHaveBeenCalledWith(
        expect.arrayContaining([expect.objectContaining({ value: 325.0 })]),
      )
      expect(setDataMock).toHaveBeenCalledWith([
        { time: '2026-09-01', value: 236.9 },
        { time: '2026-09-02', value: 236.9 },
      ])
    })

    it('renders no zone overlay (and does not crash) when only one bar is visible (PR #152 blocking finding #2: duplicate-timestamp setData crash)', async () => {
      mockHistory({
        ...twoBars,
        bars: [twoBars.bars[1]],
      })
      mockAnalysis([buildZone()])

      renderWithProviders(<PriceChart ticker="AAPL" />)

      await waitFor(() =>
        expect(screen.getByTestId('price-chart-canvas')).toBeInTheDocument(),
      )
      // Candlestick + value-zone (2) + EMA13/EMA26 (2) + channel (2) +
      // tide-region shading (1 -- only 1 bar/point survives the
      // `selectVisibleIndicatorPoints` window, forming a single segment) =
      // 8 -- no BaselineSeries, since a single visible bar can't form the
      // 2-distinct-timestamp span a zone band needs (setData would
      // otherwise throw on a duplicate timestamp, per Lightweight Charts'
      // own strictly-ascending-time assertion). The tide-region shading has
      // no such minimum -- a single-bar segment still renders as one valid
      // (if boundary-less) data point.
      await waitFor(() => expect(addSeriesMock).toHaveBeenCalledTimes(8))
      expect(
        addSeriesMock.mock.calls.some(
          ([definition]) => definition === 'BaselineSeries-definition',
        ),
      ).toBe(false)
    })

    it('renders no zone overlay when every returned zone is filtered out as irrelevant to the latest close', async () => {
      mockHistory(twoBars)
      mockAnalysis([
        // Both far above (and, for the second, far below) the 229.7 latest
        // close -- unlike the "excludes a zone far from the latest close"
        // test above, NOTHING survives the relevance filter here.
        buildZone({ upper: 2350.0, lower: 2300.0 }),
        buildZone({ upper: 20.0, lower: 15.0 }),
      ])

      renderWithProviders(<PriceChart ticker="AAPL" />)

      await waitFor(() =>
        expect(screen.getByTestId('price-chart-canvas')).toBeInTheDocument(),
      )
      // Candlestick + value-zone (2) + EMA13/EMA26 (2) + channel (2) +
      // tide-region shading (1) = 8 -- same as the "no zones detected"
      // case, since none of the returned zones are eligible to be drawn.
      await waitFor(() => expect(addSeriesMock).toHaveBeenCalledTimes(8))
      expect(
        addSeriesMock.mock.calls.some(
          ([definition]) => definition === 'BaselineSeries-definition',
        ),
      ).toBe(false)
      // Post-review fix (PR #152 retry round 2): the legend itself must
      // also disappear when nothing survives the relevance filter -- not
      // just the chart bands -- since a legend describing zones that
      // aren't actually drawn is exactly the bug this fix addresses.
      expect(screen.queryByText('Support/Resistance Zones')).not.toBeInTheDocument()
      expect(screen.queryByText('False Breakout')).not.toBeInTheDocument()
    })

    it("keeps the legend's \"Showing N of M\" count and \"Nearest to the latest close\" reading consistent with the zones actually drawn, when some zones are filtered out as irrelevant (PR #152 retry round 2 regression)", async () => {
      mockHistory(twoBars)
      const relevantResistance = buildZone({
        role: 'resistance',
        upper: 231.0,
        lower: 229.9,
        strength_score: 10,
      })
      const irrelevantHighStrength = buildZone({
        // Far pre-split-era-style level, well outside the 50% relevance
        // window around the 229.7 latest close, but given the HIGHEST
        // strength_score so a bug that searches "nearest"/counts "shown"
        // over the raw (unfiltered) zones list would surface it.
        role: 'support',
        upper: 2350.0,
        lower: 2300.0,
        strength_score: 100,
      })
      mockAnalysis([irrelevantHighStrength, relevantResistance])
      const user = userEvent.setup()

      renderWithProviders(<PriceChart ticker="AAPL" />)

      await waitFor(() =>
        expect(screen.getByText('Support/Resistance Zones')).toBeInTheDocument(),
      )
      // Only the one relevant zone actually reaches `setData`/the pane.
      await waitFor(() => {
        const baselineCalls = addSeriesMock.mock.calls.filter(
          ([definition]) => definition === 'BaselineSeries-definition',
        )
        expect(baselineCalls).toHaveLength(1)
      })

      await user.click(
        screen.getByRole('button', { name: 'Support/Resistance Zones help' }),
      )
      // The legend must report 1 of 2 (the actually-displayed count), never
      // the raw zones.length, and must name the relevant resistance zone as
      // "nearest" -- never the far, unrendered support zone, even though it
      // has the highest strength_score.
      expect(screen.getByText(/Showing 1 of 2 detected zones/)).toBeInTheDocument()
      expect(screen.getByText(/Resistance 229\.90-231\.00/)).toBeInTheDocument()
      expect(screen.queryByText(/2300\.00-2350\.00/)).not.toBeInTheDocument()
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

  describe('divergence overlay (frontend-divergence-markers)', () => {
    it('draws a connecting line + circle markers between the two compared price swing points, distinct from BUY/SELL markers', async () => {
      mockHistory(barsSpanningDivergence)
      mockAnalysis([], { divergence: bullishDivergence })

      renderWithProviders(<PriceChart ticker="AAPL" />)

      await waitFor(() =>
        expect(screen.getByTestId('price-chart-canvas')).toBeInTheDocument(),
      )

      // The connecting line spans the two extreme dates at their own PRICE
      // (not indicator value) -- first_extreme_price/second_extreme_price.
      await waitFor(() =>
        expect(setDataMock).toHaveBeenCalledWith([
          { time: '2026-08-03', value: 210.5 },
          { time: '2026-08-31', value: 205.2 },
        ]),
      )

      // Two `createSeriesMarkers` calls total: the BUY/SELL transition
      // markers (signal overlay) and this divergence pair -- find the one
      // with 'circle' shapes (BUY/SELL uses 'arrowUp'/'arrowDown', see
      // `buildOverlayData`).
      const divergenceMarkersCall = createSeriesMarkersMock.mock.calls.find(
        ([, markers]) =>
          Array.isArray(markers) &&
          (markers as { shape: string }[]).every((marker) => marker.shape === 'circle'),
      )
      expect(divergenceMarkersCall).toBeDefined()
      const markers = divergenceMarkersCall?.[1] as {
        time: string
        shape: string
        text: string
      }[]
      expect(markers).toHaveLength(2)
      expect(markers.map((marker) => marker.time)).toEqual(['2026-08-03', '2026-08-31'])
      expect(markers.every((marker) => marker.text === 'Bullish divergence')).toBe(true)
    })

    it('draws nothing when there is no currently-qualifying divergence', async () => {
      mockHistory(twoBars)
      mockAnalysis([], { divergence: null })

      renderWithProviders(<PriceChart ticker="AAPL" />)

      await waitFor(() =>
        expect(screen.getByTestId('price-chart-canvas')).toBeInTheDocument(),
      )
      await waitFor(() => expect(createSeriesMarkersMock).toHaveBeenCalled())

      expect(screen.queryByRole('button', { name: 'Divergence help' })).not.toBeInTheDocument()
      const divergenceMarkersCall = createSeriesMarkersMock.mock.calls.find(
        ([, markers]) =>
          Array.isArray(markers) &&
          (markers as { shape: string }[]).some((marker) => marker.shape === 'circle'),
      )
      expect(divergenceMarkersCall).toBeUndefined()
    })

    it('shows the Divergence legend naming the actual two dates/values compared for this ticker', async () => {
      const user = userEvent.setup()
      mockHistory(barsSpanningDivergence)
      mockAnalysis([], { divergence: bullishDivergence })

      renderWithProviders(<PriceChart ticker="AAPL" />)

      await waitFor(() => expect(screen.getByText('Divergence')).toBeInTheDocument())

      await user.click(screen.getByRole('button', { name: 'Divergence help' }))

      expect(
        screen.getByText(/Bullish MACD-Histogram divergence/),
      ).toBeInTheDocument()
      expect(screen.getByText(/2026-08-03/)).toBeInTheDocument()
      expect(screen.getByText(/2026-08-31/)).toBeInTheDocument()
      expect(screen.getByText(/210.50/)).toBeInTheDocument()
      expect(screen.getByText(/205.20/)).toBeInTheDocument()
    })

    it('opens a balloon explaining the divergence when a divergence marker (either extreme date) is clicked', async () => {
      mockHistory(barsSpanningDivergence)
      mockAnalysis([], { divergence: bullishDivergence })

      renderWithProviders(<PriceChart ticker="AAPL" />)

      await waitFor(() => expect(subscribeClickMock).toHaveBeenCalled())
      const handleClick = subscribeClickMock.mock.calls[0][0] as (param: unknown) => void

      expect(screen.queryByLabelText('Divergence details')).not.toBeInTheDocument()

      handleClick({
        time: '2026-08-31',
        point: { x: 10, y: 10 },
        sourceEvent: { pageX: 123, pageY: 45 },
        seriesData: new Map(),
      })

      expect(await screen.findByLabelText('Divergence details')).toBeInTheDocument()
      expect(
        within(screen.getByLabelText('Divergence details')).getByText(
          /Bullish MACD-Histogram divergence/,
        ),
      ).toBeInTheDocument()
    })

    it('does not open the balloon for a click on an unrelated date', async () => {
      mockHistory(barsSpanningDivergence)
      mockAnalysis([], { divergence: bullishDivergence })

      renderWithProviders(<PriceChart ticker="AAPL" />)

      await waitFor(() => expect(subscribeClickMock).toHaveBeenCalled())
      const handleClick = subscribeClickMock.mock.calls[0][0] as (param: unknown) => void

      handleClick({
        time: '2026-09-01',
        point: { x: 10, y: 10 },
        sourceEvent: { pageX: 123, pageY: 45 },
        seriesData: new Map(),
      })

      expect(screen.queryByLabelText('Divergence details')).not.toBeInTheDocument()
    })

    it('does not open the balloon when the click event carries no page coordinates', async () => {
      mockHistory(barsSpanningDivergence)
      mockAnalysis([], { divergence: bullishDivergence })

      renderWithProviders(<PriceChart ticker="AAPL" />)

      await waitFor(() => expect(subscribeClickMock).toHaveBeenCalled())
      const handleClick = subscribeClickMock.mock.calls[0][0] as (param: unknown) => void

      handleClick({
        time: '2026-08-31',
        point: { x: 10, y: 10 },
        sourceEvent: {},
        seriesData: new Map(),
      })

      expect(screen.queryByLabelText('Divergence details')).not.toBeInTheDocument()
    })

    it('closes the divergence balloon on Escape', async () => {
      const user = userEvent.setup()
      mockHistory(barsSpanningDivergence)
      mockAnalysis([], { divergence: bullishDivergence })

      renderWithProviders(<PriceChart ticker="AAPL" />)

      await waitFor(() => expect(subscribeClickMock).toHaveBeenCalled())
      const handleClick = subscribeClickMock.mock.calls[0][0] as (param: unknown) => void
      handleClick({
        time: '2026-08-31',
        point: { x: 10, y: 10 },
        sourceEvent: { pageX: 123, pageY: 45 },
        seriesData: new Map(),
      })
      expect(await screen.findByLabelText('Divergence details')).toBeInTheDocument()

      await user.keyboard('{Escape}')

      expect(screen.queryByLabelText('Divergence details')).not.toBeInTheDocument()
    })

    it('removes the previous divergence line/markers/click subscription and adds new ones when the divergence changes', async () => {
      mockHistory(barsSpanningDivergence)
      mockAnalysis([], { divergence: bullishDivergence })
      const queryClient = createTestQueryClient()

      renderWithProviders(<PriceChart ticker="AAPL" />, { queryClient })

      await waitFor(() => expect(subscribeClickMock).toHaveBeenCalledTimes(1))

      const otherDivergence: DivergenceOut = {
        ...bullishDivergence,
        second_extreme_date: '2026-09-01',
        second_extreme_price: 208.0,
      }
      mockAnalysis([], { divergence: otherDivergence })
      await queryClient.invalidateQueries({ queryKey: stocksKeys.analysis('AAPL') })

      await waitFor(() =>
        expect(setDataMock).toHaveBeenCalledWith([
          { time: '2026-08-03', value: 210.5 },
          { time: '2026-09-01', value: 208.0 },
        ]),
      )
      // The candlestick chart itself was never recreated for an
      // analysis-only refetch...
      expect(createChartMock).toHaveBeenCalledTimes(1)
      // ...but the stale divergence overlay's own line series, markers
      // plugin, and click subscription were torn down before the new ones
      // were added.
      expect(unsubscribeClickMock).toHaveBeenCalledTimes(1)
      expect(detachMarkersMock).toHaveBeenCalled()
      expect(subscribeClickMock).toHaveBeenCalledTimes(2)
    })

    // Post-review fix (PR #158, blocking finding): the divergence overlay
    // must be windowed to the currently visible bar range, the same
    // pattern PR #152 already established for
    // selectDisplayedZones/buildFalseBreakoutMarkers -- an unwindowed
    // connecting line whose own points sit outside the visible range
    // stretched Lightweight Charts' time scale to cover the gap, squashing
    // the candlestick chart into an unreadable sliver (reproduced live on
    // AAPL switching from 1Y to 1M). `twoBars` (2026-09-01/02) deliberately
    // excludes `bullishDivergence`'s own dates (2026-08-03/08-31).
    it('does not draw the connecting line/markers/click subscription when the divergence dates fall outside the currently visible bar range', async () => {
      mockHistory(twoBars)
      mockAnalysis([], { divergence: bullishDivergence })

      renderWithProviders(<PriceChart ticker="AAPL" />)

      await waitFor(() =>
        expect(screen.getByTestId('price-chart-canvas')).toBeInTheDocument(),
      )
      // Give the BUY/SELL signal-overlay markers a chance to be added first
      // so this assertion isn't just "nothing has rendered yet".
      await waitFor(() => expect(createSeriesMarkersMock).toHaveBeenCalled())

      const divergenceMarkersCall = createSeriesMarkersMock.mock.calls.find(
        ([, markers]) =>
          Array.isArray(markers) &&
          (markers as { shape: string }[]).some((marker) => marker.shape === 'circle'),
      )
      expect(divergenceMarkersCall).toBeUndefined()
      const divergenceLineData = setDataMock.mock.calls.find(
        ([data]) =>
          Array.isArray(data) && (data as { time: string }[])[0]?.time === '2026-08-03',
      )
      expect(divergenceLineData).toBeUndefined()
      expect(subscribeClickMock).not.toHaveBeenCalled()
    })

    it('still shows the Divergence legend (noting it is not in the current range) when the divergence dates fall outside the currently visible bar range', async () => {
      const user = userEvent.setup()
      mockHistory(twoBars)
      mockAnalysis([], { divergence: bullishDivergence })

      renderWithProviders(<PriceChart ticker="AAPL" />)

      await waitFor(() => expect(screen.getByText(/Divergence/)).toBeInTheDocument())
      expect(screen.getByText('Divergence (not in current range)')).toBeInTheDocument()

      await user.click(screen.getByRole('button', { name: 'Divergence help' }))

      // Still names the actual ticker-specific divergence...
      expect(
        screen.getByText(/Bullish MACD-Histogram divergence/),
      ).toBeInTheDocument()
      expect(screen.getByText(/2026-08-03/)).toBeInTheDocument()
      // ...plus the out-of-range explanation.
      expect(
        screen.getByText(/isn’t drawn on the chart right now/),
      ).toBeInTheDocument()
    })
  })

  describe('kangaroo tail overlay (frontend-kangaroo-tail-markers)', () => {
    it('draws a square marker at the tail bar itself plus a dashed suggested-stop price line, distinct from every other marker type', async () => {
      mockHistory(barsSpanningKangarooTail)
      mockAnalysis([], { kangaroo_tail: upwardKangarooTail })

      renderWithProviders(<PriceChart ticker="AAPL" />)

      await waitFor(() =>
        expect(screen.getByTestId('price-chart-canvas')).toBeInTheDocument(),
      )

      // Distinct `square` shape -- BUY/SELL use `arrowUp`/`arrowDown`,
      // divergence uses `circle`, false breakouts use `arrowDown`/`arrowUp`.
      const kangarooTailMarkersCall = createSeriesMarkersMock.mock.calls.find(
        ([, markers]) =>
          Array.isArray(markers) &&
          (markers as { shape: string }[]).every((marker) => marker.shape === 'square'),
      )
      expect(kangarooTailMarkersCall).toBeDefined()
      const markers = kangarooTailMarkersCall?.[1] as {
        time: string
        position: string
        shape: string
        text: string
      }[]
      expect(markers).toEqual([
        {
          time: '2026-08-15',
          position: 'aboveBar',
          shape: 'square',
          color: expect.any(String),
          text: 'Kangaroo Tail (bearish)',
        },
      ])

      await waitFor(() => expect(createPriceLineMock).toHaveBeenCalledTimes(1))
      expect(createPriceLineMock).toHaveBeenCalledWith(
        expect.objectContaining({ price: 226.83, title: 'Kangaroo Tail stop' }),
      )
    })

    it('positions a downward (bullish) tail marker belowBar', async () => {
      mockHistory(barsSpanningKangarooTail)
      mockAnalysis([], {
        kangaroo_tail: { ...upwardKangarooTail, direction: 'down' },
      })

      renderWithProviders(<PriceChart ticker="AAPL" />)

      await waitFor(() =>
        expect(screen.getByTestId('price-chart-canvas')).toBeInTheDocument(),
      )

      const kangarooTailMarkersCall = createSeriesMarkersMock.mock.calls.find(
        ([, markers]) =>
          Array.isArray(markers) &&
          (markers as { shape: string }[]).every((marker) => marker.shape === 'square'),
      )
      const markers = kangarooTailMarkersCall?.[1] as {
        position: string
        text: string
      }[]
      expect(markers).toEqual([
        expect.objectContaining({ position: 'belowBar', text: 'Kangaroo Tail (bullish)' }),
      ])
    })

    it('draws nothing when there is no currently confirmed Kangaroo Tail', async () => {
      mockHistory(twoBars)
      mockAnalysis([], { kangaroo_tail: null })

      renderWithProviders(<PriceChart ticker="AAPL" />)

      await waitFor(() =>
        expect(screen.getByTestId('price-chart-canvas')).toBeInTheDocument(),
      )
      await waitFor(() => expect(createSeriesMarkersMock).toHaveBeenCalled())

      expect(
        screen.queryByRole('button', { name: 'Kangaroo Tail help' }),
      ).not.toBeInTheDocument()
      const kangarooTailMarkersCall = createSeriesMarkersMock.mock.calls.find(
        ([, markers]) =>
          Array.isArray(markers) &&
          (markers as { shape: string }[]).some((marker) => marker.shape === 'square'),
      )
      expect(kangarooTailMarkersCall).toBeUndefined()
      expect(createPriceLineMock).not.toHaveBeenCalled()
    })

    it("shows the Kangaroo Tail legend with MetricHelp content using this tail's own actual numbers (range vs. average, open/close vs. the extreme, suggested stop)", async () => {
      const user = userEvent.setup()
      mockHistory(barsSpanningKangarooTail)
      mockAnalysis([], { kangaroo_tail: upwardKangarooTail })

      renderWithProviders(<PriceChart ticker="AAPL" />)

      await waitFor(() => expect(screen.getByText('Kangaroo Tail')).toBeInTheDocument())

      await user.click(screen.getByRole('button', { name: 'Kangaroo Tail help' }))

      expect(screen.getByText(/Bearish \(upward-pointing\) Kangaroo Tail/)).toBeInTheDocument()
      // The bar's own range (233.00 - 220.66 = 12.34) vs. the ~4.41 recent
      // average implied by range_multiple 2.8.
      expect(screen.getByText(/12.34/)).toBeInTheDocument()
      expect(screen.getByText(/~4.41 average range/)).toBeInTheDocument()
      // Open/close from the actual OHLCV bar found by date, not from
      // KangarooTailOut itself (which only exposes high/low).
      expect(screen.getByText(/228.00/)).toBeInTheDocument()
      expect(screen.getByText(/222.50/)).toBeInTheDocument()
      expect(screen.getByText(/Suggested stop: 226.83/)).toBeInTheDocument()
    })

    it('removes the previous marker/price line and adds new ones when the tail changes', async () => {
      mockHistory(barsSpanningKangarooTail)
      mockAnalysis([], { kangaroo_tail: upwardKangarooTail })
      const queryClient = createTestQueryClient()

      renderWithProviders(<PriceChart ticker="AAPL" />, { queryClient })

      await waitFor(() => expect(createPriceLineMock).toHaveBeenCalledTimes(1))
      expect(createPriceLineMock).toHaveBeenCalledWith(
        expect.objectContaining({ price: 226.83, title: 'Kangaroo Tail stop' }),
      )

      const otherTail: KangarooTailOut = {
        ...upwardKangarooTail,
        direction: 'down',
        suggested_stop: 224.5,
      }
      mockAnalysis([], { kangaroo_tail: otherTail })
      await queryClient.invalidateQueries({ queryKey: stocksKeys.analysis('AAPL') })

      await waitFor(() =>
        expect(createPriceLineMock).toHaveBeenCalledWith(
          expect.objectContaining({ price: 224.5, title: 'Kangaroo Tail stop' }),
        ),
      )
      // The candlestick chart itself was never recreated for an
      // analysis-only refetch...
      expect(createChartMock).toHaveBeenCalledTimes(1)
      // ...but the stale marker plugin/price line were torn down before the
      // new ones were added.
      expect(detachMarkersMock).toHaveBeenCalled()
      expect(removePriceLineMock).toHaveBeenCalled()
    })

    it('does not draw the marker/price line when the tail date falls outside the currently visible bar range', async () => {
      mockHistory(twoBars)
      mockAnalysis([], { kangaroo_tail: upwardKangarooTail })

      renderWithProviders(<PriceChart ticker="AAPL" />)

      await waitFor(() =>
        expect(screen.getByTestId('price-chart-canvas')).toBeInTheDocument(),
      )
      await waitFor(() => expect(createSeriesMarkersMock).toHaveBeenCalled())

      const kangarooTailMarkersCall = createSeriesMarkersMock.mock.calls.find(
        ([, markers]) =>
          Array.isArray(markers) &&
          (markers as { shape: string }[]).some((marker) => marker.shape === 'square'),
      )
      expect(kangarooTailMarkersCall).toBeUndefined()
      expect(createPriceLineMock).not.toHaveBeenCalled()
    })

    it('still shows the Kangaroo Tail legend (noting it is not in the current range) when the tail date falls outside the currently visible bar range', async () => {
      const user = userEvent.setup()
      mockHistory(twoBars)
      mockAnalysis([], { kangaroo_tail: upwardKangarooTail })

      renderWithProviders(<PriceChart ticker="AAPL" />)

      await waitFor(() => expect(screen.getByText(/Kangaroo Tail/)).toBeInTheDocument())
      expect(screen.getByText('Kangaroo Tail (not in current range)')).toBeInTheDocument()

      await user.click(screen.getByRole('button', { name: 'Kangaroo Tail help' }))

      expect(screen.getByText(/Bearish \(upward-pointing\) Kangaroo Tail/)).toBeInTheDocument()
      expect(screen.getByText(/isn't marked on the chart right now/)).toBeInTheDocument()
    })
  })
})
