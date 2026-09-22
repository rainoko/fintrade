import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { server } from '../../../../tests/mocks/server'
import { renderWithProviders } from '../../../../tests/renderWithProviders'
import StockCharts from './StockCharts'

// jsdom mock, same approach as PriceChart.test.tsx/OscillatorChart.test.tsx
// — this file cares about the range/interval wiring *between* PriceChart
// and OscillatorChart, not chart-library internals.
vi.mock('lightweight-charts', () => ({
  createChart: () => ({
    addSeries: () => ({
      setData: () => {},
      createPriceLine: () => ({}),
      removePriceLine: () => {},
      // `setSeriesOrder` (frontend-channel-overlay, post-review fix) — see
      // PriceChart.test.tsx's own mock for the fuller explanation.
      setSeriesOrder: () => {},
      // `series.priceScale()` (frontend-tide-region-chart-shading) — an
      // empty stub is enough here too, same "this file doesn't assert on
      // it" rationale as `panes` below. Must be a per-series method (not
      // `chart.priceScale(id)`) — see PriceChart.test.tsx's own mock for
      // why the real library requires that.
      priceScale: () => ({ applyOptions: () => {} }),
    }),
    removeSeries: () => {},
    // `bringSeriesToFront` (utils/chart.ts, frontend-support-resistance-
    // overlay) reads `panes()[0].getSeries().length` — this file doesn't
    // assert on series ordering (see the top comment), so an empty stub is
    // enough to keep it from throwing.
    panes: () => [{ getSeries: () => [] }],
    timeScale: () => ({ fitContent: () => {} }),
    remove: () => {},
  }),
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
})
