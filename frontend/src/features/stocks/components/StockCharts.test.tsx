import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { HistoryResponse } from '../../../api/stocks'
import { server } from '../../../../tests/mocks/server'
import { renderWithProviders } from '../../../../tests/renderWithProviders'
import StockCharts from './StockCharts'

// `GET /api/stocks/{ticker}/history` legitimately returns null
// open/high/low/close for today's still-forming (not yet closed) trading
// day (yfinance NaN OHLC, serialized as JSON null) even though the
// generated `HistoryResponse['bars']` type says `number` -- same
// real-world shape `PriceChart.test.tsx`'s own `formingBar` fixture
// constructs, via a single cast, for the exact same reason.
const formingBar = {
  date: '2026-09-03',
  open: null,
  high: null,
  low: null,
  close: null,
  volume: 12345,
} as unknown as HistoryResponse['bars'][number]

// jsdom mock, same approach as PriceChart.test.tsx/OscillatorChart.test.tsx
// — this file cares about the range/interval wiring *between* PriceChart
// and OscillatorChart, not chart-library internals. Each chart instance
// tracks its own pane's REAL series z-order (not just an empty stub) so the
// frontend-support-zones-disappear-after-oscillators regression test below
// (which asserts on the actual final stacking order once multiple series
// get added across renders) can tell a genuinely-fixed order from a broken
// one — same technique, same rationale, as PriceChart.test.tsx's own
// `createChartMock`.
interface MockSeries {
  setSeriesOrder: (index: number) => void
}
interface MockChart {
  panes: () => { getSeries: () => unknown[] }[]
  // `(definition, series)` pairs in creation order -- lets a test identify
  // e.g. "the sole CandlestickSeries-definition instance" without needing
  // its own separate `addSeriesMock` spy (StockCharts.tsx's own components
  // all share this ONE mocked module, so a single per-chart record here is
  // simpler than threading a shared spy through).
  createdSeries: { definition: unknown; series: MockSeries }[]
}
const createdCharts: MockChart[] = []
vi.mock('lightweight-charts', () => ({
  createChart: (): MockChart => {
    const paneSeries: MockSeries[] = []
    const createdSeries: { definition: unknown; series: MockSeries }[] = []
    const chart = {
      addSeries: (definition: unknown) => {
        const created: MockSeries & Record<string, unknown> = {
          setData: () => {},
          createPriceLine: () => ({}),
          removePriceLine: () => {},
          priceScale: () => ({ applyOptions: () => {} }),
          setSeriesOrder: (index: number) => {
            const currentIndex = paneSeries.indexOf(created)
            if (currentIndex !== -1) {
              paneSeries.splice(currentIndex, 1)
            }
            paneSeries.splice(index, 0, created)
          },
        }
        paneSeries.push(created)
        createdSeries.push({ definition, series: created })
        return created
      },
      removeSeries: (series: MockSeries) => {
        const index = paneSeries.indexOf(series)
        if (index !== -1) {
          paneSeries.splice(index, 1)
        }
      },
      panes: () => [{ getSeries: () => [...paneSeries] }],
      timeScale: () => ({ fitContent: () => {} }),
      remove: () => {},
      createdSeries,
    }
    createdCharts.push(chart)
    return chart
  },
  createSeriesMarkers: () => ({ setMarkers: () => {}, detach: () => {} }),
  CandlestickSeries: 'CandlestickSeries-definition',
  LineSeries: 'LineSeries-definition',
  HistogramSeries: 'HistogramSeries-definition',
  AreaSeries: 'AreaSeries-definition',
  BaselineSeries: 'BaselineSeries-definition',
  LineStyle: { Solid: 0, Dotted: 1, Dashed: 2, LargeDashed: 3, SparseDotted: 4 },
}))

let lastIndicatorsRange: string | null = null

describe('StockCharts', () => {
  beforeEach(() => {
    lastIndicatorsRange = null
    createdCharts.length = 0
    server.use(
      http.get('/api/stocks/:ticker/indicators', ({ request }) => {
        lastIndicatorsRange = new URL(request.url).searchParams.get('range')
        return HttpResponse.json({
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
              obv: 12345000.0,
              accumulation_distribution: 6789000.0,
              trend_strength: { atr: 3.8, plus_di: 26.0, minus_di: 18.5, adx: 20.0 },
              signal: 'HOLD',
              confidence: 0,
              confidence_band: 'Low',
            },
          ],
        })
      }),
      http.get('/api/stocks/:ticker/history', ({ request }) => {
        const url = new URL(request.url)
        const interval = (url.searchParams.get('interval') ?? 'daily') as
          'daily' | 'weekly'
        return HttpResponse.json({
          ticker: 'AAPL',
          interval,
          bars: [
            {
              date: '2026-09-01',
              open: 227.1,
              high: 229.4,
              low: 226.8,
              close: 228.9,
              volume: 51234000,
            },
          ],
        })
      }),
    )
  })

  it('mirrors the price chart range selection into the oscillator pane', async () => {
    const user = userEvent.setup()

    renderWithProviders(<StockCharts ticker="AAPL" />)

    await waitFor(() =>
      expect(screen.getByTestId('price-chart-canvas')).toBeInTheDocument(),
    )
    await waitFor(() =>
      expect(screen.getByTestId('oscillator-chart-canvas')).toBeInTheDocument(),
    )
    expect(lastIndicatorsRange).toBe('1y')

    const rangeGroup = screen.getByRole('group', { name: 'Price history range' })
    await user.click(within(rangeGroup).getByRole('button', { name: '3M' }))

    await waitFor(() => expect(lastIndicatorsRange).toBe('3m'))
    // The oscillator pane re-fetched and re-rendered for the new range
    // rather than staying stuck on the old one.
    await waitFor(() =>
      expect(screen.getByTestId('oscillator-chart-canvas')).toBeInTheDocument(),
    )
  })

  it('hides the oscillator pane (with an explanatory message) once Weekly interval is selected, and restores it on Daily', async () => {
    const user = userEvent.setup()

    renderWithProviders(<StockCharts ticker="AAPL" />)

    await waitFor(() =>
      expect(screen.getByTestId('oscillator-chart-canvas')).toBeInTheDocument(),
    )

    const intervalGroup = screen.getByRole('group', { name: 'Price history interval' })
    await user.click(within(intervalGroup).getByRole('button', { name: 'Weekly' }))

    await waitFor(() =>
      expect(
        screen.getByText(
          'Oscillators (Stochastic %K, RSI, Force Index, MACD Histogram) are only available for the Daily interval.',
        ),
      ).toBeInTheDocument(),
    )
    expect(screen.queryByTestId('oscillator-chart-canvas')).not.toBeInTheDocument()

    await user.click(within(intervalGroup).getByRole('button', { name: 'Daily' }))

    await waitFor(() =>
      expect(screen.getByTestId('oscillator-chart-canvas')).toBeInTheDocument(),
    )
  })

  // Follow-up (frontend-volume-indicators-chart-followups): the standalone
  // VolumeIndicatorsChart.test.tsx already exercises the component in
  // isolation, but nothing previously asserted it's actually wired
  // correctly (range/enabled props) inside the composed StockCharts page,
  // the way this file already did for OscillatorChart above -- a future
  // edit that silently broke the StockCharts->VolumeIndicatorsChart wiring
  // (e.g. swapping range/enabled props between panes) wouldn't have been
  // caught by either suite. Mirrors the two OscillatorChart tests above.
  it('mirrors the price chart range selection into the volume indicators pane', async () => {
    const user = userEvent.setup()

    renderWithProviders(<StockCharts ticker="AAPL" />)

    await waitFor(() =>
      expect(screen.getByTestId('price-chart-canvas')).toBeInTheDocument(),
    )
    await waitFor(() =>
      expect(screen.getByTestId('volume-indicators-chart-canvas')).toBeInTheDocument(),
    )
    expect(lastIndicatorsRange).toBe('1y')

    const rangeGroup = screen.getByRole('group', { name: 'Price history range' })
    await user.click(within(rangeGroup).getByRole('button', { name: '3M' }))

    await waitFor(() => expect(lastIndicatorsRange).toBe('3m'))
    // The volume indicators pane re-fetched and re-rendered for the new
    // range rather than staying stuck on the old one.
    await waitFor(() =>
      expect(screen.getByTestId('volume-indicators-chart-canvas')).toBeInTheDocument(),
    )
  })

  it('hides the volume indicators pane (with an explanatory message) once Weekly interval is selected, and restores it on Daily', async () => {
    const user = userEvent.setup()

    renderWithProviders(<StockCharts ticker="AAPL" />)

    await waitFor(() =>
      expect(screen.getByTestId('volume-indicators-chart-canvas')).toBeInTheDocument(),
    )

    const intervalGroup = screen.getByRole('group', { name: 'Price history interval' })
    await user.click(within(intervalGroup).getByRole('button', { name: 'Weekly' }))

    await waitFor(() =>
      expect(
        screen.getByText(
          'Volume indicators (OBV, A/D) are only available for the Daily interval.',
        ),
      ).toBeInTheDocument(),
    )
    expect(screen.queryByTestId('volume-indicators-chart-canvas')).not.toBeInTheDocument()

    await user.click(within(intervalGroup).getByRole('button', { name: 'Daily' }))

    await waitFor(() =>
      expect(screen.getByTestId('volume-indicators-chart-canvas')).toBeInTheDocument(),
    )
  })

  // Follow-up (frontend-position-risk-columns-followups-followups-followups):
  // PriceChart, OscillatorChart, VolumeIndicatorsChart, and TrendStrengthChart
  // all call the same useIndicatorHistory(ticker, { range }) hook/query key,
  // so before this fix a single GET /api/stocks/{ticker}/indicators failure
  // rendered four identical stacked common/ErrorState alerts -- the same
  // sibling-duplication shape already fixed on PortfolioPage (PR #258) and
  // DashboardPage (PR #259). This regression test asserts the page-level
  // composition specifically, since each chart's own standalone test can't
  // catch a duplicate that only appears once all four are mounted together.
  it('shows exactly one alert (not four stacked) when GET /api/stocks/:ticker/indicators fails, with all four charts mounted', async () => {
    server.use(
      http.get('/api/stocks/:ticker/indicators', () =>
        HttpResponse.json({ detail: 'boom' }, { status: 500 }),
      ),
    )

    renderWithProviders(<StockCharts ticker="AAPL" />)

    const alerts = await screen.findAllByRole('alert')
    expect(alerts).toHaveLength(1)
    // PriceChart is the sole error surface for this shared failure --
    // OscillatorChart/VolumeIndicatorsChart/TrendStrengthChart render
    // nothing (no own alert, no own loading/empty state) for it.
    expect(screen.queryByTestId('oscillator-chart-canvas')).not.toBeInTheDocument()
    expect(screen.queryByTestId('volume-indicators-chart-canvas')).not.toBeInTheDocument()
    expect(screen.queryByTestId('trend-strength-chart-canvas')).not.toBeInTheDocument()
  })

  // Compound-failure regression (frontend-position-risk-columns-followups-
  // followups-followups-followups, checklist item 1): PriceChart's own
  // indicators-ErrorState used to be gated behind `showOverlaySection`
  // (`historyQuery.isSuccess && hasBars && overlayEnabled`), a condition
  // about *price history*, not about whether `/indicators` itself failed.
  // OscillatorChart/VolumeIndicatorsChart/TrendStrengthChart all suppress
  // their own indicators-ErrorState (via `errorSurfacedBySibling`, passed by
  // StockCharts.tsx above), relying on PriceChart to be the shared
  // failure's sole surface -- so when `/history` ALSO fails (or succeeds
  // with zero usable bars), `showOverlaySection` was false and a genuinely
  // failed `/indicators` never rendered anywhere at all. PriceChart.tsx now
  // gates that ErrorState on `overlayEnabled` alone, independent of
  // `showOverlaySection`, fixing this.
  it('still surfaces a genuine GET /api/stocks/:ticker/indicators failure when GET /api/stocks/:ticker/history ALSO fails', async () => {
    server.use(
      http.get('/api/stocks/:ticker/history', () =>
        HttpResponse.json(
          { detail: 'Market data provider is currently unavailable. Try again shortly.' },
          { status: 503 },
        ),
      ),
      http.get('/api/stocks/:ticker/indicators', () =>
        HttpResponse.json({ detail: 'Unknown ticker: AAPL' }, { status: 404 }),
      ),
    )

    renderWithProviders(<StockCharts ticker="AAPL" />)

    const alerts = await screen.findAllByRole('alert')
    // One alert for the /history failure, one for the /indicators failure
    // -- both from PriceChart (historyQuery.isError and, now un-gated from
    // showOverlaySection, indicatorsQuery.isError). The three sibling
    // charts still render nothing of their own (errorSurfacedBySibling).
    expect(alerts).toHaveLength(2)
    expect(screen.getByText('Service unavailable')).toBeInTheDocument()
    expect(screen.getByText('Not found')).toBeInTheDocument()
    expect(screen.queryByTestId('oscillator-chart-canvas')).not.toBeInTheDocument()
    expect(screen.queryByTestId('volume-indicators-chart-canvas')).not.toBeInTheDocument()
    expect(screen.queryByTestId('trend-strength-chart-canvas')).not.toBeInTheDocument()
  })

  it('still surfaces a genuine GET /api/stocks/:ticker/indicators failure when GET /api/stocks/:ticker/history succeeds with zero usable bars', async () => {
    server.use(
      http.get('/api/stocks/:ticker/history', ({ request }) => {
        const url = new URL(request.url)
        const interval = (url.searchParams.get('interval') ?? 'daily') as
          'daily' | 'weekly'
        return HttpResponse.json({ ticker: 'AAPL', interval, bars: [formingBar] })
      }),
      http.get('/api/stocks/:ticker/indicators', () =>
        HttpResponse.json({ detail: 'Unknown ticker: AAPL' }, { status: 404 }),
      ),
    )

    renderWithProviders(<StockCharts ticker="AAPL" />)

    // The price chart itself degrades to its EmptyState (no usable bars)...
    await waitFor(() =>
      expect(screen.getByText('No price history available for AAPL.')).toBeInTheDocument(),
    )
    // ...but the /indicators failure is still visible, even though
    // showOverlaySection (which requires hasBars) is false.
    const alerts = await screen.findAllByRole('alert')
    expect(alerts).toHaveLength(1)
    expect(screen.getByText('Not found')).toBeInTheDocument()
    expect(screen.queryByTestId('oscillator-chart-canvas')).not.toBeInTheDocument()
    expect(screen.queryByTestId('volume-indicators-chart-canvas')).not.toBeInTheDocument()
    expect(screen.queryByTestId('trend-strength-chart-canvas')).not.toBeInTheDocument()
  })

  // Regression test for a user-reported bug (frontend-support-zones-
  // disappear-after-oscillators): PriceChart's own support/resistance zone
  // bands rendered correctly on initial load, then disappeared once
  // OscillatorChart finished loading its own data. Investigated with the
  // real components mounted together (as this task's checklist calls for),
  // not just PriceChart in isolation, since that's the shape the bug was
  // originally reported in -- even though the root cause (see PriceChart.
  // test.tsx's own regression test and this task's `decisions` entry) turned
  // out to be entirely internal to PriceChart's own effects: OscillatorChart
  // never touches PriceChart's chart at all, and "zones disappear once
  // Oscillators finishes loading" is purely coincidental timing off the one
  // GET /api/stocks/{ticker}/indicators query both happen to depend on
  // independently.
  it('keeps PriceChart\'s support/resistance zone bands in front of its own later-added fill series once OscillatorChart finishes loading (both mounted together, as reported)', async () => {
    let resolveIndicators: (() => void) | undefined
    server.use(
      // The zone effect (PriceChart.tsx) skips drawing anything at all with
      // fewer than 2 visible bars (PR #152 duplicate-timestamp guard) --
      // this file's own default `/history` override above returns only one,
      // so this test needs its own two-bar override to actually exercise
      // the zone bands.
      http.get('/api/stocks/:ticker/history', () =>
        HttpResponse.json({
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
        }),
      ),
      http.get('/api/stocks/:ticker/indicators', async ({ request }) => {
        lastIndicatorsRange = new URL(request.url).searchParams.get('range')
        await new Promise<void>((resolve) => {
          resolveIndicators = resolve
        })
        return HttpResponse.json({
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
              obv: 12345000.0,
              accumulation_distribution: 6789000.0,
              trend_strength: { atr: 3.8, plus_di: 26.0, minus_di: 18.5, adx: 20.0 },
              signal: 'HOLD',
              confidence: 0,
              confidence_band: 'Low',
            },
          ],
        })
      }),
    )

    renderWithProviders(<StockCharts ticker="AAPL" />)

    // PriceChart's own zone effect has already run (the default MSW
    // `/analysis` fixture includes one zone -- see tests/mocks/handlers.ts)
    // while `/indicators` -- and therefore OscillatorChart -- is still
    // loading.
    await waitFor(() =>
      expect(screen.getByText('Loading oscillator history for AAPL...')).toBeInTheDocument(),
    )
    await waitFor(() => expect(resolveIndicators).toBeDefined())
    const priceChart = createdCharts[0]!
    await waitFor(() =>
      expect(
        priceChart.createdSeries.some(
          ({ definition }) => definition === 'BaselineSeries-definition',
        ),
      ).toBe(true),
    )

    resolveIndicators?.()

    // OscillatorChart has now finished loading -- the exact moment the
    // reported bug happened.
    await waitFor(() =>
      expect(screen.getByTestId('oscillator-chart-canvas')).toBeInTheDocument(),
    )
    // PriceChart's own signal-overlay/tide-region effects have finished
    // adding their fill series too.
    await waitFor(() => expect(priceChart.createdSeries.length).toBeGreaterThan(2))

    const finalOrder = priceChart.panes()[0]!.getSeries()
    const candlestickSeries = priceChart.createdSeries.find(
      ({ definition }) => definition === 'CandlestickSeries-definition',
    )!.series
    const zoneBandSeries = priceChart.createdSeries.find(
      ({ definition }) => definition === 'BaselineSeries-definition',
    )!.series

    // Still the topmost (unchanged existing invariant) -- but the zone band
    // now sits directly beneath it, above every value-zone/tide-region fill
    // series PriceChart's own later-running effects added once
    // `/indicators` (and therefore OscillatorChart) finished loading,
    // instead of being buried underneath them (the reported bug).
    expect(finalOrder.indexOf(candlestickSeries)).toBe(finalOrder.length - 1)
    expect(finalOrder.indexOf(zoneBandSeries)).toBe(finalOrder.length - 2)
  })
})
