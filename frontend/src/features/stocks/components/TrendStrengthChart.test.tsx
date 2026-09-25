import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { IndicatorHistoryResponse } from '../../../api/stocks'
import { server } from '../../../../tests/mocks/server'
import { renderWithProviders } from '../../../../tests/renderWithProviders'
import TrendStrengthChart from './TrendStrengthChart'

// jsdom has no real <canvas> 2D context, and Lightweight Charts' own
// resize/rendering internals aren't available/meaningful in this
// environment either — same mocking approach as
// PriceChart.test.tsx/OscillatorChart.test.tsx/VolumeIndicatorsChart.test.tsx.
const setDataMock = vi.fn()
const removeMock = vi.fn()
const fitContentMock = vi.fn()
const addSeriesMock = vi.fn(
  (_definition: unknown, _options: { title?: string }, paneIndex?: number) => ({
    setData: (data: unknown) => setDataMock(paneIndex, data),
  }),
)
const createChartMock = vi.fn(() => ({
  addSeries: addSeriesMock,
  timeScale: () => ({ fitContent: fitContentMock }),
  remove: removeMock,
}))

vi.mock('lightweight-charts', () => ({
  createChart: () => createChartMock(),
  LineSeries: 'LineSeries-definition',
}))

function mockIndicators(response: IndicatorHistoryResponse) {
  server.use(
    http.get('/api/stocks/:ticker/indicators', () => HttpResponse.json(response)),
  )
}

const indicatorPoints: IndicatorHistoryResponse = {
  ticker: 'AAPL',
  trading_mode: { mode: 'swing', day_trader_timeframe_triple: null },
  points: [
    {
      date: '2026-09-01',
      tide: { trend: 'BULLISH', weekly_macd_histogram_slope: 'rising' },
      ema_13: 225.1,
      ema_26: 220.4,
      macd_histogram: 1.2,
      bull_power: 2.5,
      bear_power: -1.1,
      obv: 5000.0,
      accumulation_distribution: 1200.0,
      trend_strength: { atr: 3.8, plus_di: 26.0, minus_di: 18.5, adx: 20.0 },
      signal: 'HOLD',
      confidence: 0,
      confidence_band: 'Low',
    },
    {
      date: '2026-09-02',
      tide: { trend: 'BULLISH', weekly_macd_histogram_slope: 'rising' },
      ema_13: 226.4,
      ema_26: 221.7,
      macd_histogram: -1.82,
      bull_power: 3.1,
      bear_power: -1.4,
      obv: 10500.0,
      accumulation_distribution: 900.0,
      trend_strength: { atr: 4.2, plus_di: 28.5, minus_di: 15.3, adx: 24.0 },
      signal: 'BUY',
      confidence: 72,
      confidence_band: 'High',
    },
  ],
}

// A bar still inside ADX's own (longer) warm-up window, plus one where
// `trend_strength` itself is entirely absent from the payload (a malformed
// response no real backend would send, since `trend_strength` is typed
// always-present — exercising this component's own defense-in-depth `?.`
// guard, same rationale as `VolumeIndicatorsChart.test.tsx`'s own
// `nonFinitePoint`).
const warmingUpPoint: IndicatorHistoryResponse['points'][number] = {
  date: '2026-08-30',
  tide: { trend: 'BULLISH', weekly_macd_histogram_slope: 'rising' },
  ema_13: 224.0,
  ema_26: 219.5,
  macd_histogram: 0.9,
  bull_power: 2.0,
  bear_power: -0.9,
  obv: 4000.0,
  accumulation_distribution: 1000.0,
  trend_strength: { atr: 3.5, plus_di: 24.0, minus_di: 20.0, adx: null },
  signal: 'HOLD',
  confidence: 0,
  confidence_band: 'Low',
}

const missingTrendStrengthPoint = {
  date: '2026-08-31',
  tide: { trend: 'BULLISH', weekly_macd_histogram_slope: 'rising' },
  ema_13: 224.5,
  ema_26: 219.8,
  macd_histogram: 1.0,
  bull_power: 2.1,
  bear_power: -1.0,
  signal: 'HOLD',
  confidence: 0,
  confidence_band: 'Low',
} as unknown as IndicatorHistoryResponse['points'][number]

describe('TrendStrengthChart', () => {
  beforeEach(() => {
    setDataMock.mockClear()
    removeMock.mockClear()
    fitContentMock.mockClear()
    addSeriesMock.mockClear()
    createChartMock.mockClear()
  })

  it('shows a loading state, then renders +DI/-DI/ADX on pane 0 and ATR on pane 1', async () => {
    mockIndicators(indicatorPoints)

    renderWithProviders(<TrendStrengthChart ticker="AAPL" range="1y" />)

    expect(
      screen.getByText('Loading trend strength history for AAPL...'),
    ).toBeInTheDocument()

    await waitFor(() =>
      expect(screen.getByTestId('trend-strength-chart-canvas')).toBeInTheDocument(),
    )

    expect(addSeriesMock).toHaveBeenCalledTimes(4)
    expect(addSeriesMock.mock.calls.map((call) => call[2])).toEqual([0, 0, 0, 1])
    expect(addSeriesMock.mock.calls[0][1]).toMatchObject({ title: '+DI (13)' })
    expect(addSeriesMock.mock.calls[1][1]).toMatchObject({ title: '-DI (13)' })
    expect(addSeriesMock.mock.calls[2][1]).toMatchObject({ title: 'ADX (13)' })
    expect(addSeriesMock.mock.calls[3][1]).toMatchObject({ title: 'ATR (13)' })

    const plusDiData = setDataMock.mock.calls[0][1]
    expect(plusDiData).toEqual([
      { time: '2026-09-01', value: 26.0 },
      { time: '2026-09-02', value: 28.5 },
    ])
    const minusDiData = setDataMock.mock.calls[1][1]
    expect(minusDiData).toEqual([
      { time: '2026-09-01', value: 18.5 },
      { time: '2026-09-02', value: 15.3 },
    ])
    const adxData = setDataMock.mock.calls[2][1]
    expect(adxData).toEqual([
      { time: '2026-09-01', value: 20.0 },
      { time: '2026-09-02', value: 24.0 },
    ])
    const atrData = setDataMock.mock.calls[3][1]
    expect(atrData).toEqual([
      { time: '2026-09-01', value: 3.8 },
      { time: '2026-09-02', value: 4.2 },
    ])
    expect(fitContentMock).toHaveBeenCalledTimes(1)
  })

  it('omits a still-warming-up ADX value from its own series without affecting +DI/-DI/ATR', async () => {
    mockIndicators({
      ticker: 'AAPL',
      trading_mode: { mode: 'swing', day_trader_timeframe_triple: null },
      points: [warmingUpPoint, ...indicatorPoints.points],
    })

    renderWithProviders(<TrendStrengthChart ticker="AAPL" range="max" />)

    await waitFor(() =>
      expect(screen.getByTestId('trend-strength-chart-canvas')).toBeInTheDocument(),
    )

    const plusDiData = setDataMock.mock.calls[0][1] as { time: string }[]
    expect(plusDiData.map((point) => point.time)).toEqual([
      '2026-08-30',
      '2026-09-01',
      '2026-09-02',
    ])
    const adxData = setDataMock.mock.calls[2][1] as { time: string }[]
    expect(adxData.map((point) => point.time)).toEqual(['2026-09-01', '2026-09-02'])
  })

  it('tolerates a point with trend_strength entirely absent instead of crashing', async () => {
    mockIndicators({
      ticker: 'AAPL',
      trading_mode: { mode: 'swing', day_trader_timeframe_triple: null },
      points: [missingTrendStrengthPoint, ...indicatorPoints.points],
    })

    renderWithProviders(<TrendStrengthChart ticker="AAPL" range="max" />)

    await waitFor(() =>
      expect(screen.getByTestId('trend-strength-chart-canvas')).toBeInTheDocument(),
    )

    const plusDiData = setDataMock.mock.calls[0][1] as { time: string }[]
    expect(plusDiData.map((point) => point.time)).toEqual(['2026-09-01', '2026-09-02'])
  })

  it('shows an EmptyState instead of a broken chart when the API returns zero points', async () => {
    mockIndicators({
      ticker: 'AAPL',
      trading_mode: { mode: 'swing', day_trader_timeframe_triple: null },
      points: [],
    })

    renderWithProviders(<TrendStrengthChart ticker="AAPL" range="1y" />)

    await waitFor(() =>
      expect(
        screen.getByText('No trend strength history available for AAPL.'),
      ).toBeInTheDocument(),
    )
    expect(screen.queryByTestId('trend-strength-chart-canvas')).not.toBeInTheDocument()
    expect(createChartMock).not.toHaveBeenCalled()
  })

  // This chart shares the exact same useIndicatorHistory hook/query key with
  // PriceChart, OscillatorChart, and VolumeIndicatorsChart (all composed
  // together by StockCharts.tsx). By default it still renders its own
  // common/ErrorState on indicatorsQuery.isError -- a standalone mount (no
  // errorSurfacedBySibling-passing sibling) must still surface a real fetch
  // failure. Only a caller that explicitly passes errorSurfacedBySibling
  // (StockCharts.tsx, since PriceChart already owns this shared failure's
  // ErrorState) opts out -- see this component's own prop doc comment and
  // the frontend-position-risk-columns-followups-followups-followups-
  // followups task's decisions entry.
  it('renders its own ErrorState on a 404 for an unknown ticker by default (no errorSurfacedBySibling)', async () => {
    renderWithProviders(<TrendStrengthChart ticker="UNKNOWN" range="1y" />)

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    expect(screen.getByText('Not found')).toBeInTheDocument()
    expect(screen.queryByTestId('trend-strength-chart-canvas')).not.toBeInTheDocument()
  })

  it('renders nothing (no own ErrorState) on a 404 when errorSurfacedBySibling is passed, since PriceChart owns this shared failure', async () => {
    renderWithProviders(
      <TrendStrengthChart ticker="UNKNOWN" range="1y" errorSurfacedBySibling />,
    )

    await waitFor(() =>
      expect(
        screen.queryByText('Loading trend strength history for UNKNOWN...'),
      ).not.toBeInTheDocument(),
    )
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.queryByTestId('trend-strength-chart-canvas')).not.toBeInTheDocument()
  })

  it('does not fetch or render when disabled (weekly interval upstream), showing an explanatory message instead', async () => {
    let requestCount = 0
    server.use(
      http.get('/api/stocks/:ticker/indicators', () => {
        requestCount += 1
        return HttpResponse.json(indicatorPoints)
      }),
    )

    renderWithProviders(<TrendStrengthChart ticker="AAPL" range="1y" enabled={false} />)

    expect(
      screen.getByText(
        'Trend strength indicators (+DI, -DI, ADX, ATR) are only available for the Daily interval.',
      ),
    ).toBeInTheDocument()
    expect(screen.queryByTestId('trend-strength-chart-canvas')).not.toBeInTheDocument()
    expect(createChartMock).not.toHaveBeenCalled()
    expect(requestCount).toBe(0)
  })

  it('refetches with the selected range and recreates the chart when the range prop changes', async () => {
    let lastRequestedRange: string | null = null
    server.use(
      http.get('/api/stocks/:ticker/indicators', ({ request }) => {
        lastRequestedRange = new URL(request.url).searchParams.get('range')
        return HttpResponse.json(indicatorPoints)
      }),
    )

    const { rerender } = renderWithProviders(
      <TrendStrengthChart ticker="AAPL" range="1y" />,
    )

    await waitFor(() =>
      expect(screen.getByTestId('trend-strength-chart-canvas')).toBeInTheDocument(),
    )
    expect(lastRequestedRange).toBe('1y')
    expect(createChartMock).toHaveBeenCalledTimes(1)

    rerender(<TrendStrengthChart ticker="AAPL" range="3m" />)

    await waitFor(() => expect(lastRequestedRange).toBe('3m'))
    await waitFor(() => expect(createChartMock).toHaveBeenCalledTimes(2))
    expect(removeMock).toHaveBeenCalledTimes(1)
  })

  it('shows +DI/-DI, ADX, and ATR legend rows with MetricHelp affordances once the chart resolves', async () => {
    mockIndicators(indicatorPoints)

    renderWithProviders(<TrendStrengthChart ticker="AAPL" range="1y" />)

    await waitFor(() =>
      expect(screen.getByTestId('trend-strength-chart-canvas')).toBeInTheDocument(),
    )

    expect(screen.getByText('+DI / -DI (13)')).toBeInTheDocument()
    expect(screen.getByText('ADX (13)')).toBeInTheDocument()
    expect(screen.getByText('ATR (13)')).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: '+DI / -DI (13) help' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'ADX (13) help' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'ATR (13) help' })).toBeInTheDocument()
  })

  it('opens the +DI/-DI MetricHelp balloon naming which direction currently leads', async () => {
    mockIndicators(indicatorPoints)
    const user = userEvent.setup()

    renderWithProviders(<TrendStrengthChart ticker="AAPL" range="1y" />)

    await waitFor(() =>
      expect(screen.getByTestId('trend-strength-chart-canvas')).toBeInTheDocument(),
    )

    await user.click(screen.getByRole('button', { name: '+DI / -DI (13) help' }))

    // Latest bar: +DI 28.5 vs -DI 15.3 -- +DI leads.
    expect(screen.getByText(/\+DI leads/)).toBeInTheDocument()
  })

  it('opens the ADX MetricHelp balloon describing the rise off its own recent low', async () => {
    mockIndicators(indicatorPoints)
    const user = userEvent.setup()

    renderWithProviders(<TrendStrengthChart ticker="AAPL" range="1y" />)

    await waitFor(() =>
      expect(screen.getByTestId('trend-strength-chart-canvas')).toBeInTheDocument(),
    )

    await user.click(screen.getByRole('button', { name: 'ADX (13) help' }))

    // ADX rose from 20.0 to 24.0 (its own low over the window) -- a 4.0
    // point rise, exactly at Elder's own "rings a bell" threshold.
    expect(screen.getByText(/risen 4\.0 points/)).toBeInTheDocument()
    expect(screen.getByText(/at or beyond Elder's own 4-point/)).toBeInTheDocument()
  })

  it('opens the ATR MetricHelp balloon stating the current value and the 1-ATR stop-distance rule', async () => {
    mockIndicators(indicatorPoints)
    const user = userEvent.setup()

    renderWithProviders(<TrendStrengthChart ticker="AAPL" range="1y" />)

    await waitFor(() =>
      expect(screen.getByTestId('trend-strength-chart-canvas')).toBeInTheDocument(),
    )

    await user.click(screen.getByRole('button', { name: 'ATR (13) help' }))

    expect(screen.getByText(/Currently 4\.20/)).toBeInTheDocument()
    expect(screen.getByText(/closer than 1 ATR/)).toBeInTheDocument()
  })
})
