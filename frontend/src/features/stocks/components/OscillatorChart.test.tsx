import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { IndicatorHistoryResponse } from '../../../api/stocks'
import { server } from '../../../../tests/mocks/server'
import { renderWithProviders } from '../../../../tests/renderWithProviders'
import OscillatorChart from './OscillatorChart'

// jsdom has no real <canvas> 2D context, and Lightweight Charts' own
// resize/rendering internals aren't available/meaningful in this
// environment either — mocking the whole module is the same approach
// PriceChart.test.tsx uses. `createPriceLine` (the 30/70 Stochastic
// reference lines and the Force Index/MACD Histogram zero baselines) and
// `HistogramSeries`/`LineStyle` are new here versus PriceChart's own mock,
// which never used either.
const setDataMock = vi.fn()
const removeMock = vi.fn()
const fitContentMock = vi.fn()
const createPriceLineMock = vi.fn()
const addSeriesMock = vi.fn(
  (_definition: unknown, _options: unknown, paneIndex?: number) => ({
    setData: (data: unknown) => setDataMock(paneIndex, data),
    createPriceLine: (options: unknown) => createPriceLineMock(paneIndex, options),
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
  HistogramSeries: 'HistogramSeries-definition',
  LineStyle: { Solid: 0, Dotted: 1, Dashed: 2, LargeDashed: 3, SparseDotted: 4 },
}))

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
      rsi: 48.2,
      force_index_2ema: 1000.0,
      signal: 'HOLD',
      confidence: 0,
      confidence_band: 'Low',
    },
    {
      date: '2026-09-02',
      ema_13: 226.4,
      ema_26: 221.7,
      macd_histogram: -1.82,
      bull_power: 3.1,
      bear_power: -1.4,
      stochastic_k: 24.3,
      rsi: 29.5,
      force_index_2ema: -18234.5,
      signal: 'BUY',
      confidence: 72,
      confidence_band: 'High',
    },
  ],
}

// GET /api/stocks/{ticker}/indicators legitimately returns null
// stochastic_k/force_index_2ema/macd_histogram for early bars still inside
// an indicator's warm-up window (e.g. Stochastic %K(5,3,3) needs ~11 prior
// bars) -- confirmed live via GET /api/stocks/AAPL/indicators?range=max,
// which returns points with these fields literally `null` -- even though
// the generated `IndicatorHistoryPoint` type says `number`, since that's
// what the real backend does. Built via a single cast (rather than `as any`
// on each field) to construct that real-world shape for tests despite the
// type, same pattern PriceChart.test.tsx's `formingBar` uses for null OHLC.
const warmingUpPoint = {
  date: '2026-08-31',
  ema_13: 224.0,
  ema_26: 219.5,
  macd_histogram: 0.9,
  bull_power: 2.0,
  bear_power: -0.9,
  stochastic_k: null,
  rsi: null,
  force_index_2ema: null,
  signal: 'HOLD',
  confidence: 0,
  confidence_band: 'Low',
} as unknown as IndicatorHistoryResponse['points'][number]

// The very first bar of a ticker's history has no prior data at all --
// every one of these fields can legitimately be null there, not just
// stochastic_k/rsi/force_index_2ema.
const firstEverBarPoint = {
  date: '2026-08-30',
  ema_13: 223.0,
  ema_26: 218.0,
  macd_histogram: null,
  bull_power: 1.5,
  bear_power: -1.2,
  stochastic_k: null,
  rsi: null,
  force_index_2ema: null,
  signal: 'HOLD',
  confidence: 0,
  confidence_band: 'Low',
} as unknown as IndicatorHistoryResponse['points'][number]

describe('OscillatorChart', () => {
  beforeEach(() => {
    setDataMock.mockClear()
    removeMock.mockClear()
    fitContentMock.mockClear()
    addSeriesMock.mockClear()
    createChartMock.mockClear()
    createPriceLineMock.mockClear()
  })

  it('shows a loading state, then renders Stochastic/RSI/Force Index/MACD Histogram, Stochastic+RSI sharing one pane', async () => {
    mockIndicators(indicatorPoints)

    renderWithProviders(<OscillatorChart ticker="AAPL" range="1y" />)

    expect(screen.getByText('Loading oscillator history for AAPL...')).toBeInTheDocument()

    await waitFor(() =>
      expect(screen.getByTestId('oscillator-chart-canvas')).toBeInTheDocument(),
    )

    // Stochastic %K (pane 0), RSI (also pane 0), Force Index (pane 1), MACD
    // Histogram (pane 2) — four addSeries calls, each fed straight from the
    // backend response.
    expect(addSeriesMock).toHaveBeenCalledTimes(4)
    expect(addSeriesMock.mock.calls.map((call) => call[2])).toEqual([0, 0, 1, 2])

    // First pane-0 addSeries call is Stochastic (its own setData call comes
    // first), second is RSI.
    const paneZeroSetDataCalls = setDataMock.mock.calls.filter(
      ([paneIndex]) => paneIndex === 0,
    )
    expect(paneZeroSetDataCalls).toHaveLength(2)
    expect(paneZeroSetDataCalls[0][1]).toEqual([
      { time: '2026-09-01', value: 55.0 },
      { time: '2026-09-02', value: 24.3 },
    ])
    expect(paneZeroSetDataCalls[1][1]).toEqual([
      { time: '2026-09-01', value: 48.2 },
      { time: '2026-09-02', value: 29.5 },
    ])
    expect(fitContentMock).toHaveBeenCalledTimes(1)
  })

  it('colors Force Index and MACD Histogram bars by sign, not a fixed color', async () => {
    mockIndicators(indicatorPoints)

    renderWithProviders(<OscillatorChart ticker="AAPL" range="1y" />)

    await waitFor(() =>
      expect(screen.getByTestId('oscillator-chart-canvas')).toBeInTheDocument(),
    )

    // Force Index: 1000.0 (>= 0) then -18234.5 (< 0) -- two different colors.
    const forceIndexData = setDataMock.mock.calls.find(
      ([paneIndex]) => paneIndex === 1,
    )?.[1] as {
      color: string
    }[]
    expect(forceIndexData[0].color).not.toBe(forceIndexData[1].color)

    // MACD Histogram: 1.2 (>= 0) then -1.82 (< 0) -- two different colors,
    // matching the same sign->color mapping as Force Index.
    const macdData = setDataMock.mock.calls.find(
      ([paneIndex]) => paneIndex === 2,
    )?.[1] as {
      color: string
    }[]
    expect(macdData[0].color).not.toBe(macdData[1].color)
    expect(macdData[0].color).toBe(forceIndexData[0].color)
    expect(macdData[1].color).toBe(forceIndexData[1].color)
  })

  it('adds reference lines at the documented 30/70 Stochastic thresholds, and a zero baseline for Force Index/MACD Histogram', async () => {
    mockIndicators(indicatorPoints)

    renderWithProviders(<OscillatorChart ticker="AAPL" range="1y" />)

    await waitFor(() =>
      expect(screen.getByTestId('oscillator-chart-canvas')).toBeInTheDocument(),
    )

    const stochasticLines = createPriceLineMock.mock.calls
      .filter(([paneIndex]) => paneIndex === 0)
      .map(([, options]) => options as { price: number; title: string })
    expect(stochasticLines).toHaveLength(2)
    expect(stochasticLines.map((line) => line.price).sort((a, b) => a - b)).toEqual([
      30, 70,
    ])
    expect(stochasticLines.find((line) => line.price === 30)?.title).toContain('Oversold')
    expect(stochasticLines.find((line) => line.price === 70)?.title).toContain(
      'Overbought',
    )

    const forceIndexLines = createPriceLineMock.mock.calls
      .filter(([paneIndex]) => paneIndex === 1)
      .map(([, options]) => options as { price: number })
    expect(forceIndexLines.map((line) => line.price)).toEqual([0])

    const macdLines = createPriceLineMock.mock.calls
      .filter(([paneIndex]) => paneIndex === 2)
      .map(([, options]) => options as { price: number })
    expect(macdLines.map((line) => line.price)).toEqual([0])
  })

  it('filters out non-finite stochastic_k/rsi/force_index_2ema values per-series instead of crashing (PR #108 review regression)', async () => {
    // Reproduces the reported crash: selecting a range that includes bars
    // still inside the indicator warm-up window (e.g. "Max") used to pass a
    // literal `null` straight into Lightweight Charts' `setData`, which
    // throws synchronously ("Line series item data value must be a number,
    // got=object, value=null") -- uncaught, that crashed the whole app via
    // AppErrorBoundary, not just this pane.
    mockIndicators({
      ticker: 'AAPL',
      points: [firstEverBarPoint, warmingUpPoint, ...indicatorPoints.points],
    })

    renderWithProviders(<OscillatorChart ticker="AAPL" range="max" />)

    await waitFor(() =>
      expect(screen.getByTestId('oscillator-chart-canvas')).toBeInTheDocument(),
    )

    // Stochastic %K and RSI (both pane 0): the warm-up point's null
    // stochastic_k/rsi is omitted entirely from each -- a gap in the line,
    // not a crash and not the whole series being suppressed (the two
    // well-formed points still plot in both series).
    const paneZeroSetDataCalls = setDataMock.mock.calls.filter(
      ([paneIndex]) => paneIndex === 0,
    )
    expect(paneZeroSetDataCalls).toHaveLength(2)
    expect(paneZeroSetDataCalls[0][1]).toEqual([
      { time: '2026-09-01', value: 55.0 },
      { time: '2026-09-02', value: 24.3 },
    ])
    expect(paneZeroSetDataCalls[1][1]).toEqual([
      { time: '2026-09-01', value: 48.2 },
      { time: '2026-09-02', value: 29.5 },
    ])

    // Force Index (pane 1): same gap treatment for its own null value.
    const forceIndexData = setDataMock.mock.calls.find(
      ([paneIndex]) => paneIndex === 1,
    )?.[1] as {
      time: string
      value: number
    }[]
    expect(forceIndexData.map((point) => point.time)).toEqual([
      '2026-09-01',
      '2026-09-02',
    ])

    // MACD Histogram (pane 2): only the very first bar (which has no macd
    // value yet either) is dropped -- the warm-up point had a finite
    // macd_histogram, so it is NOT dropped there. Each series is filtered
    // independently, not the whole point removed from every series just
    // because one field was null.
    const macdData = setDataMock.mock.calls.find(
      ([paneIndex]) => paneIndex === 2,
    )?.[1] as {
      time: string
      value: number
    }[]
    expect(macdData.map((point) => point.time)).toEqual([
      '2026-08-31',
      '2026-09-01',
      '2026-09-02',
    ])
  })

  it('shows an EmptyState instead of a broken chart when the API returns zero points', async () => {
    mockIndicators({ ticker: 'AAPL', points: [] })

    renderWithProviders(<OscillatorChart ticker="AAPL" range="1y" />)

    await waitFor(() =>
      expect(
        screen.getByText('No oscillator history available for AAPL.'),
      ).toBeInTheDocument(),
    )
    expect(screen.queryByTestId('oscillator-chart-canvas')).not.toBeInTheDocument()
    expect(createChartMock).not.toHaveBeenCalled()
  })

  it('shows a 404 error via common/ErrorState for an unknown ticker', async () => {
    renderWithProviders(<OscillatorChart ticker="UNKNOWN" range="1y" />)

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    expect(screen.getByText('Not found')).toBeInTheDocument()
  })

  it('shows a 503 error via common/ErrorState when the market data provider is unavailable', async () => {
    renderWithProviders(<OscillatorChart ticker="NOPROVIDER" range="1y" />)

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    expect(screen.getByText('Service unavailable')).toBeInTheDocument()
  })

  it('shows a 422 error via common/ErrorState for insufficient weekly history', async () => {
    renderWithProviders(<OscillatorChart ticker="THINHISTORY" range="1y" />)

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    expect(screen.getByText('Unable to process request')).toBeInTheDocument()
  })

  it('does not fetch or render when disabled (weekly interval upstream), showing an explanatory message instead', async () => {
    let requestCount = 0
    server.use(
      http.get('/api/stocks/:ticker/indicators', () => {
        requestCount += 1
        return HttpResponse.json(indicatorPoints)
      }),
    )

    renderWithProviders(<OscillatorChart ticker="AAPL" range="1y" enabled={false} />)

    expect(
      screen.getByText(
        'Oscillators (Stochastic %K, RSI, Force Index, MACD Histogram) are only available for the Daily interval.',
      ),
    ).toBeInTheDocument()
    expect(screen.queryByTestId('oscillator-chart-canvas')).not.toBeInTheDocument()
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

    const { rerender } = renderWithProviders(<OscillatorChart ticker="AAPL" range="1y" />)

    await waitFor(() =>
      expect(screen.getByTestId('oscillator-chart-canvas')).toBeInTheDocument(),
    )
    expect(lastRequestedRange).toBe('1y')
    expect(createChartMock).toHaveBeenCalledTimes(1)

    rerender(<OscillatorChart ticker="AAPL" range="3m" />)

    await waitFor(() => expect(lastRequestedRange).toBe('3m'))
    await waitFor(() => expect(createChartMock).toHaveBeenCalledTimes(2))
    expect(removeMock).toHaveBeenCalledTimes(1)
  })

  it('shows an RSI legend row with a MetricHelp affordance once the chart resolves', async () => {
    mockIndicators(indicatorPoints)

    renderWithProviders(<OscillatorChart ticker="AAPL" range="1y" />)

    await waitFor(() =>
      expect(screen.getByTestId('oscillator-chart-canvas')).toBeInTheDocument(),
    )

    expect(screen.getByText('RSI (9)')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'RSI (9) help' })).toBeInTheDocument()
  })

  it('opens the RSI MetricHelp balloon explaining the RSI-vs-Stochastic comparison and the current value', async () => {
    mockIndicators(indicatorPoints)
    const user = userEvent.setup()

    renderWithProviders(<OscillatorChart ticker="AAPL" range="1y" />)

    await waitFor(() =>
      expect(screen.getByTestId('oscillator-chart-canvas')).toBeInTheDocument(),
    )

    await user.click(screen.getByRole('button', { name: 'RSI (9) help' }))

    // Elder's own RSI-vs-Stochastic comparison (closing-price-only, less
    // noisy, earlier signals) from this task's description must actually
    // appear in the help content, not just a bare definition.
    expect(screen.getByText(/less noisy/)).toBeInTheDocument()
    expect(screen.getByText(/closing prices/)).toBeInTheDocument()

    // Latest point (09-02): rsi 29.5, stochastic_k 24.3 -- current-value
    // interpretation, not just a static definition.
    expect(screen.getByText(/Currently 29\.5, oversold/)).toBeInTheDocument()
  })

  it('reports the RSI value as unavailable when the latest bar is still inside the warm-up window', async () => {
    mockIndicators({
      ticker: 'AAPL',
      points: [{ ...indicatorPoints.points[0] }, { ...warmingUpPoint }],
    })
    const user = userEvent.setup()

    renderWithProviders(<OscillatorChart ticker="AAPL" range="1y" />)

    await waitFor(() =>
      expect(screen.getByTestId('oscillator-chart-canvas')).toBeInTheDocument(),
    )

    await user.click(screen.getByRole('button', { name: 'RSI (9) help' }))

    expect(screen.getByText(/unavailable for this ticker/)).toBeInTheDocument()
  })
})
