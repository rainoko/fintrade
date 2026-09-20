import { screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { server } from '../../tests/mocks/server'
import {
  createTestQueryClient,
  renderWithProviders,
} from '../../tests/renderWithProviders'
import StockDetailPage from './StockDetailPage'

// StockCharts (rendered below IndicatorsPanel) composes PriceChart and
// OscillatorChart, both of which build a real Lightweight Charts chart
// against a DOM container; jsdom has no real <canvas> 2D context, so mock
// the library the same way PriceChart.test.tsx/OscillatorChart.test.tsx do
// — this page's own tests care about page composition (which panels
// render, in what order, for which signal), not chart internals.
// `createPriceLine` (used by OscillatorChart's 30/70 and zero reference
// lines) and `HistogramSeries`/`LineStyle` (used by OscillatorChart's Force
// Index/MACD Histogram panes) are new here versus PriceChart's own overlay,
// which never called either.
vi.mock('lightweight-charts', () => ({
  createChart: () => ({
    addSeries: () => ({
      setData: () => {},
      createPriceLine: () => ({}),
      removePriceLine: () => {},
      // `setSeriesOrder` (frontend-channel-overlay, post-review fix): called
      // on PriceChart's candlestick series to keep it rendering above the
      // value-zone fill/mask and support/resistance zone band series — see
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
    // assert on series ordering, so an empty stub is enough to keep it from
    // throwing.
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

function renderStockDetail(ticker: string) {
  return renderWithProviders(
    <MemoryRouter initialEntries={[`/stocks/${ticker}`]}>
      <Routes>
        <Route path="/stocks/:ticker" element={<StockDetailPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('StockDetailPage', () => {
  it('shows a loading state, then the BUY signal, confidence, screens, and indicators', async () => {
    renderStockDetail('AAPL')

    expect(screen.getByText('Loading analysis for AAPL...')).toBeInTheDocument()

    await waitFor(() =>
      expect(screen.getByTestId('signal-badge')).toHaveTextContent('BUY'),
    )

    expect(screen.getByRole('heading', { name: 'AAPL' })).toBeInTheDocument()
    expect(screen.getByText('As of 2026-09-11')).toBeInTheDocument()
    expect(screen.getByText('72% · High')).toBeInTheDocument()
    expect(
      screen.getByRole('table', { name: 'Confidence breakdown' }),
    ).toBeInTheDocument()

    expect(screen.getByText('Tide (Screen 1)')).toBeInTheDocument()
    expect(screen.getByText('Bullish')).toBeInTheDocument()
    expect(screen.getByText('GREEN')).toBeInTheDocument()
    expect(screen.getByText('Oversold pullback')).toBeInTheDocument()
    expect(screen.getByText('Close above prior high')).toBeInTheDocument()

    expect(screen.getByText('EMA (13)')).toBeInTheDocument()
    expect(screen.getByText('226.40')).toBeInTheDocument()

    // The reused ticker entry point is present so a different ticker can be
    // looked up without navigating back to the Dashboard.
    expect(screen.getByLabelText('Look up a ticker')).toBeInTheDocument()

    // PriceChart (GET /.../history) is wired in below the indicators, per
    // this task's checklist.
    expect(screen.getByRole('group', { name: 'Price history range' })).toBeInTheDocument()
    await waitFor(() =>
      expect(screen.getByTestId('price-chart-canvas')).toBeInTheDocument(),
    )
  })

  it('renders a SELL signal', async () => {
    server.use(
      http.get('/api/stocks/:ticker/analysis', ({ params }) =>
        HttpResponse.json({
          ticker: String(params.ticker).toUpperCase(),
          as_of: '2026-09-11',
          signal: 'SELL',
          confidence: 65,
          confidence_band: 'Medium',
          screens: {
            tide: { trend: 'BEARISH', weekly_macd_histogram_slope: 'falling' },
            impulse: 'RED',
            wave: {
              stochastic_k: 82.1,
              force_index_2ema: 5000,
              state: 'OVERBOUGHT_RALLY',
              showed_pullback_in_lookback: false,
              showed_rally_in_lookback: true,
            },
            trigger: { fired: true, reference: 'close_below_prior_low' },
          },
          confidence_breakdown: [
            { component: 'tide_alignment', weight: 0.3, score: 1.0 },
          ],
          indicators: {
            ema_13: 210.4,
            ema_26: 215.7,
            macd_histogram: -1.82,
            bull_power: -3.1,
            bear_power: -5.4,
          },
          // Non-optional per `AnalysisResponse.extended_data` (backend/app/api/schemas.py) --
          // a real backend response always includes it, so this fixture does too now (see
          // this task's `decisions` entry for why, and frontend-fundamental-data-panel-
          // followups.json's checklist for the guard this keeps load-bearing rather than
          // permanently defensive).
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
        }),
      ),
    )

    renderStockDetail('MSFT')

    await waitFor(() =>
      expect(screen.getByTestId('signal-badge')).toHaveTextContent('SELL'),
    )
    expect(screen.getByText('65% · Medium')).toBeInTheDocument()
    expect(screen.getByText('RED')).toBeInTheDocument()
  })

  it('renders a HOLD signal', async () => {
    server.use(
      http.get('/api/stocks/:ticker/analysis', ({ params }) =>
        HttpResponse.json({
          ticker: String(params.ticker).toUpperCase(),
          as_of: '2026-09-11',
          signal: 'HOLD',
          confidence: 35,
          confidence_band: 'Low',
          screens: {
            tide: { trend: 'NEUTRAL', weekly_macd_histogram_slope: 'flat' },
            impulse: 'BLUE',
            wave: {
              stochastic_k: 50,
              force_index_2ema: 0,
              state: 'RANGING',
              showed_pullback_in_lookback: null,
              showed_rally_in_lookback: null,
            },
            trigger: { fired: false, reference: 'no_trigger' },
          },
          confidence_breakdown: [{ component: 'tide_alignment', weight: 0.3, score: 0 }],
          indicators: {
            ema_13: 100,
            ema_26: 100,
            macd_histogram: 0,
            bull_power: 0,
            bear_power: 0,
          },
          // Non-optional per `AnalysisResponse.extended_data` -- see the SELL fixture above.
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
        }),
      ),
    )

    renderStockDetail('GOOG')

    await waitFor(() =>
      expect(screen.getByTestId('signal-badge')).toHaveTextContent('HOLD'),
    )
    expect(screen.getByText('35% · Low')).toBeInTheDocument()
    expect(screen.getByText('BLUE')).toBeInTheDocument()
  })

  it('wires indicators.season from the analysis response through to the Indicator Season badge', async () => {
    server.use(
      http.get('/api/stocks/:ticker/analysis', ({ params }) =>
        HttpResponse.json({
          ticker: String(params.ticker).toUpperCase(),
          as_of: '2026-09-11',
          signal: 'BUY',
          confidence: 72,
          confidence_band: 'High',
          screens: {
            tide: { trend: 'BULLISH', weekly_macd_histogram_slope: 'rising' },
            impulse: 'GREEN',
            wave: {
              stochastic_k: 24.3,
              force_index_2ema: -18234.5,
              state: 'OVERSOLD_PULLBACK',
              showed_pullback_in_lookback: true,
              showed_rally_in_lookback: false,
            },
            trigger: { fired: true, reference: 'close_above_prior_high' },
          },
          confidence_breakdown: [
            { component: 'tide_alignment', weight: 0.3, score: 1.0 },
          ],
          indicators: {
            ema_13: 226.4,
            ema_26: 220.1,
            macd_histogram: 1.2,
            bull_power: 3.4,
            bear_power: -1.1,
            season: 'Spring',
          },
          // Non-optional per `AnalysisResponse.extended_data` -- see the SELL fixture above.
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
        }),
      ),
    )

    renderStockDetail('AAPL')

    await waitFor(() =>
      expect(screen.getByTestId('signal-badge')).toHaveTextContent('BUY'),
    )
    expect(screen.getByText('Indicator Season')).toBeInTheDocument()
    expect(screen.getByTestId('season-badge')).toHaveTextContent('Spring')
  })

  it('wires extended_data through to the FundamentalDataPanel, including the earnings warning banner', async () => {
    server.use(
      http.get('/api/stocks/:ticker/analysis', ({ params }) =>
        HttpResponse.json({
          ticker: String(params.ticker).toUpperCase(),
          as_of: '2026-09-11',
          signal: 'BUY',
          confidence: 72,
          confidence_band: 'High',
          screens: {
            tide: { trend: 'BULLISH', weekly_macd_histogram_slope: 'rising' },
            impulse: 'GREEN',
            wave: {
              stochastic_k: 24.3,
              force_index_2ema: -18234.5,
              state: 'OVERSOLD_PULLBACK',
              showed_pullback_in_lookback: true,
              showed_rally_in_lookback: false,
            },
            trigger: { fired: true, reference: 'close_above_prior_high' },
          },
          confidence_breakdown: [
            { component: 'tide_alignment', weight: 0.3, score: 1.0 },
          ],
          indicators: {
            ema_13: 226.4,
            ema_26: 220.1,
            macd_histogram: 1.2,
            bull_power: 3.4,
            bear_power: -1.1,
          },
          extended_data: {
            earnings_date: '2026-09-20',
            earnings_within_warning_days: true,
            ex_dividend_date: null,
            shares_short: 5_000_000,
            short_ratio: 3.1,
            short_percent_of_float: 0.08,
            float_shares: 40_000_000,
            insider_transactions: [],
            unavailable_reason: null,
          },
          insider_clusters: [],
        }),
      ),
    )

    renderStockDetail('AAPL')

    await waitFor(() =>
      expect(screen.getByTestId('signal-badge')).toHaveTextContent('BUY'),
    )
    expect(screen.getByTestId('earnings-warning-banner')).toHaveTextContent(
      'Earnings expected 2026-09-20 -- within the next 14 days.',
    )
    expect(screen.getByText('Short Interest')).toBeInTheDocument()
  })

  it('wires insider_clusters (a top-level sibling field to extended_data) through to the cluster callout', async () => {
    server.use(
      http.get('/api/stocks/:ticker/analysis', ({ params }) =>
        HttpResponse.json({
          ticker: String(params.ticker).toUpperCase(),
          as_of: '2026-09-11',
          signal: 'BUY',
          confidence: 72,
          confidence_band: 'High',
          screens: {
            tide: { trend: 'BULLISH', weekly_macd_histogram_slope: 'rising' },
            impulse: 'GREEN',
            wave: {
              stochastic_k: 24.3,
              force_index_2ema: -18234.5,
              state: 'OVERSOLD_PULLBACK',
              showed_pullback_in_lookback: true,
              showed_rally_in_lookback: false,
            },
            trigger: { fired: true, reference: 'close_above_prior_high' },
          },
          confidence_breakdown: [
            { component: 'tide_alignment', weight: 0.3, score: 1.0 },
          ],
          indicators: {
            ema_13: 226.4,
            ema_26: 220.1,
            macd_histogram: 1.2,
            bull_power: 3.4,
            bear_power: -1.1,
          },
          extended_data: {
            earnings_date: null,
            earnings_within_warning_days: false,
            ex_dividend_date: null,
            shares_short: null,
            short_ratio: null,
            short_percent_of_float: null,
            float_shares: null,
            insider_transactions: [
              {
                insider: 'Alice Smith',
                position: 'Director',
                transaction_text: 'Purchase at price 45.00 per share.',
                shares: 20_000,
                value: 900_000,
                start_date: '2026-08-10',
                ownership: 'D',
              },
            ],
            unavailable_reason: null,
          },
          insider_clusters: [
            {
              direction: 'buy',
              insiders: ['Alice Smith', 'Bob Jones', 'Carol White'],
              window_start_date: '2026-08-01',
              window_end_date: '2026-08-20',
              transaction_count: 3,
              total_shares: 60_000,
              total_value: 2_700_000,
            },
          ],
        }),
      ),
    )

    renderStockDetail('AAPL')

    await waitFor(() =>
      expect(screen.getByTestId('signal-badge')).toHaveTextContent('BUY'),
    )
    expect(screen.getByText('BUY CLUSTER')).toBeInTheDocument()
    expect(screen.getByTestId('insider-cluster-callout')).toHaveTextContent(
      '3 distinct insiders (Alice Smith, Bob Jones, Carol White)',
    )
  })

  it('shows a 404 error for an unknown ticker', async () => {
    renderStockDetail('UNKNOWN')

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    expect(screen.getByText('Not found')).toBeInTheDocument()
    expect(screen.getByText('Unknown ticker: UNKNOWN')).toBeInTheDocument()
  })

  it('shows a 422 error for insufficient weekly history', async () => {
    renderStockDetail('THINHISTORY')

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    expect(screen.getByText('Unable to process request')).toBeInTheDocument()
    expect(
      screen.getByText(
        'Insufficient weekly history for THINHISTORY to compute weekly indicators (< 26 weeks).',
      ),
    ).toBeInTheDocument()
  })

  it('shows a 503 error when the market data provider is unavailable', async () => {
    renderStockDetail('NOPROVIDER')

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    expect(screen.getByText('Service unavailable')).toBeInTheDocument()
    expect(
      screen.getByText(
        'Market data provider is currently unavailable. Try again shortly.',
      ),
    ).toBeInTheDocument()
  })

  it('shows a Methodology reference link regardless of load state, even on an error', async () => {
    renderStockDetail('UNKNOWN')

    expect(screen.getByRole('link', { name: /methodology reference/i })).toHaveAttribute(
      'href',
      '/methodology',
    )

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    expect(screen.getByRole('link', { name: /methodology reference/i })).toHaveAttribute(
      'href',
      '/methodology',
    )
  })

  it('normalizes a lowercase URL ticker to uppercase for both the heading and the query cache key', async () => {
    let requestCount = 0
    server.use(
      http.get('/api/stocks/:ticker/analysis', ({ params }) => {
        requestCount += 1
        return HttpResponse.json({
          ticker: String(params.ticker).toUpperCase(),
          as_of: '2026-09-11',
          signal: 'BUY',
          confidence: 72,
          confidence_band: 'High',
          screens: {
            tide: { trend: 'BULLISH', weekly_macd_histogram_slope: 'rising' },
            impulse: 'GREEN',
            wave: {
              stochastic_k: 24.3,
              force_index_2ema: -18234.5,
              state: 'OVERSOLD_PULLBACK',
              showed_pullback_in_lookback: true,
              showed_rally_in_lookback: false,
            },
            trigger: { fired: true, reference: 'close_above_prior_high' },
          },
          confidence_breakdown: [
            { component: 'tide_alignment', weight: 0.3, score: 1.0 },
          ],
          indicators: {
            ema_13: 226.4,
            ema_26: 220.1,
            macd_histogram: 1.2,
            bull_power: 3.4,
            bear_power: -1.1,
          },
          // Non-optional per `AnalysisResponse.extended_data` -- see the SELL fixture above.
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
        })
      }),
    )
    const queryClient = createTestQueryClient()

    // A hand-typed/bookmarked/externally-linked lowercase URL shows the
    // normalized uppercase heading immediately, not the raw lowercase param.
    const { rerender } = renderWithProviders(
      <MemoryRouter initialEntries={['/stocks/aapl']}>
        <Routes>
          <Route path="/stocks/:ticker" element={<StockDetailPage />} />
        </Routes>
      </MemoryRouter>,
      { queryClient },
    )

    expect(screen.getByRole('heading', { name: 'AAPL' })).toBeInTheDocument()
    await waitFor(() =>
      expect(screen.getByTestId('signal-badge')).toHaveTextContent('BUY'),
    )
    expect(requestCount).toBe(1)

    // A later visit to the uppercase form of the same ticker addresses the
    // same normalized query-cache key, so it's served from cache instead of
    // triggering a second, redundant fetch of identical data.
    rerender(
      <MemoryRouter initialEntries={['/stocks/AAPL']}>
        <Routes>
          <Route path="/stocks/:ticker" element={<StockDetailPage />} />
        </Routes>
      </MemoryRouter>,
    )

    expect(screen.getByRole('heading', { name: 'AAPL' })).toBeInTheDocument()
    await waitFor(() =>
      expect(screen.getByTestId('signal-badge')).toHaveTextContent('BUY'),
    )
    expect(requestCount).toBe(1)
  })

  it("falls back to a 'Stock Detail' header and skips the query when the route has no ticker param", () => {
    // App.tsx only ever mounts this page at `/stocks/:ticker` (a required
    // param), so this exact case can't happen through real navigation — but
    // `useParams`'s type is `string | undefined` regardless, and the
    // component defends against it (`ticker = ''`) rather than assuming the
    // route always supplies one. Exercising that fallback needs a route
    // that genuinely omits the param, hence the `:ticker?` here rather than
    // the app's own route.
    renderWithProviders(
      <MemoryRouter initialEntries={['/stocks']}>
        <Routes>
          <Route path="/stocks/:ticker?" element={<StockDetailPage />} />
        </Routes>
      </MemoryRouter>,
    )

    expect(screen.getByRole('heading', { name: 'Stock Detail' })).toBeInTheDocument()
    // useStockAnalysis is `enabled: ticker.length > 0`, so none of the
    // loading/error/data branches should render for an empty ticker.
    expect(screen.queryByText(/Loading analysis/)).not.toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})
