import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { IndicatorHistoryResponse } from '../../../api/stocks'
import { server } from '../../../../tests/mocks/server'
import { renderWithProviders } from '../../../../tests/renderWithProviders'
import VolumeIndicatorsChart from './VolumeIndicatorsChart'

// jsdom has no real <canvas> 2D context, and Lightweight Charts' own
// resize/rendering internals aren't available/meaningful in this
// environment either — same mocking approach as
// PriceChart.test.tsx/OscillatorChart.test.tsx.
const setDataMock = vi.fn()
const removeMock = vi.fn()
const fitContentMock = vi.fn()
const applyOptionsMock = vi.fn()
const addSeriesMock = vi.fn(
  (_definition: unknown, _options: { title?: string }, paneIndex?: number) => ({
    setData: (data: unknown) => setDataMock(paneIndex, data),
    applyOptions: (options: unknown) => applyOptionsMock(paneIndex, options),
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
      trend_strength: { atr: 4.2, plus_di: 28.5, minus_di: 15.3, adx: 22.1 },
      signal: 'BUY',
      confidence: 72,
      confidence_band: 'High',
    },
  ],
}

// The very first bar of a ticker's history can legitimately carry a
// non-finite value for a field with a real warm-up window elsewhere in this
// API response shape (e.g. macd_histogram) — obv/accumulation_distribution
// themselves have no warm-up window (see this component's own doc comment),
// but the runtime guard is still exercised here the same way
// OscillatorChart.test.tsx exercises its own "defense in depth" guard, by
// constructing a real-world-shaped point with an explicit non-numeric value
// despite what the generated type promises.
const nonFinitePoint = {
  date: '2026-08-31',
  ema_13: 224.0,
  ema_26: 219.5,
  macd_histogram: 0.9,
  bull_power: 2.0,
  bear_power: -0.9,
  obv: null,
  accumulation_distribution: null,
  signal: 'HOLD',
  confidence: 0,
  confidence_band: 'Low',
} as unknown as IndicatorHistoryResponse['points'][number]

describe('VolumeIndicatorsChart', () => {
  beforeEach(() => {
    setDataMock.mockClear()
    removeMock.mockClear()
    fitContentMock.mockClear()
    addSeriesMock.mockClear()
    createChartMock.mockClear()
    applyOptionsMock.mockClear()
  })

  it('shows a loading state, then renders OBV and A/D on separate panes', async () => {
    mockIndicators(indicatorPoints)

    renderWithProviders(<VolumeIndicatorsChart ticker="AAPL" range="1y" />)

    expect(
      screen.getByText('Loading volume indicator history for AAPL...'),
    ).toBeInTheDocument()

    await waitFor(() =>
      expect(screen.getByTestId('volume-indicators-chart-canvas')).toBeInTheDocument(),
    )

    expect(addSeriesMock).toHaveBeenCalledTimes(2)
    expect(addSeriesMock.mock.calls.map((call) => call[2])).toEqual([0, 1])
    expect(addSeriesMock.mock.calls[0][1]).toMatchObject({
      title: 'On-Balance Volume (OBV)',
    })
    expect(addSeriesMock.mock.calls[1][1]).toMatchObject({
      title: 'Accumulation/Distribution (A/D)',
    })

    const obvData = setDataMock.mock.calls.find(([paneIndex]) => paneIndex === 0)?.[1]
    expect(obvData).toEqual([
      { time: '2026-09-01', value: 5000.0 },
      { time: '2026-09-02', value: 10500.0 },
    ])
    const adData = setDataMock.mock.calls.find(([paneIndex]) => paneIndex === 1)?.[1]
    expect(adData).toEqual([
      { time: '2026-09-01', value: 1200.0 },
      { time: '2026-09-02', value: 900.0 },
    ])
    expect(fitContentMock).toHaveBeenCalledTimes(1)
  })

  it('filters out a non-finite obv/accumulation_distribution value per-series instead of crashing', async () => {
    mockIndicators({
      ticker: 'AAPL',
      trading_mode: { mode: 'swing', day_trader_timeframe_triple: null },
      points: [nonFinitePoint, ...indicatorPoints.points],
    })

    renderWithProviders(<VolumeIndicatorsChart ticker="AAPL" range="max" />)

    await waitFor(() =>
      expect(screen.getByTestId('volume-indicators-chart-canvas')).toBeInTheDocument(),
    )

    const obvData = setDataMock.mock.calls.find(
      ([paneIndex]) => paneIndex === 0,
    )?.[1] as {
      time: string
    }[]
    expect(obvData.map((point) => point.time)).toEqual(['2026-09-01', '2026-09-02'])
    const adData = setDataMock.mock.calls.find(([paneIndex]) => paneIndex === 1)?.[1] as {
      time: string
    }[]
    expect(adData.map((point) => point.time)).toEqual(['2026-09-01', '2026-09-02'])
  })

  it('shows an EmptyState instead of a broken chart when the API returns zero points', async () => {
    mockIndicators({
      ticker: 'AAPL',
      trading_mode: { mode: 'swing', day_trader_timeframe_triple: null },
      points: [],
    })

    renderWithProviders(<VolumeIndicatorsChart ticker="AAPL" range="1y" />)

    await waitFor(() =>
      expect(
        screen.getByText('No volume indicator history available for AAPL.'),
      ).toBeInTheDocument(),
    )
    expect(screen.queryByTestId('volume-indicators-chart-canvas')).not.toBeInTheDocument()
    expect(createChartMock).not.toHaveBeenCalled()
  })

  // This chart shares the exact same useIndicatorHistory hook/query key with
  // PriceChart, OscillatorChart, and TrendStrengthChart (all composed
  // together by StockCharts.tsx). By default it still renders its own
  // common/ErrorState on indicatorsQuery.isError -- a standalone mount (no
  // errorSurfacedBySibling-passing sibling) must still surface a real fetch
  // failure. Only a caller that explicitly passes errorSurfacedBySibling
  // (StockCharts.tsx, since PriceChart already owns this shared failure's
  // ErrorState) opts out -- see this component's own prop doc comment and
  // the frontend-position-risk-columns-followups-followups-followups-
  // followups task's decisions entry.
  it('renders its own ErrorState on a 404 for an unknown ticker by default (no errorSurfacedBySibling)', async () => {
    renderWithProviders(<VolumeIndicatorsChart ticker="UNKNOWN" range="1y" />)

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    expect(screen.getByText('Not found')).toBeInTheDocument()
    expect(screen.queryByTestId('volume-indicators-chart-canvas')).not.toBeInTheDocument()
  })

  it('renders nothing (no own ErrorState) on a 404 when errorSurfacedBySibling is passed, since PriceChart owns this shared failure', async () => {
    renderWithProviders(
      <VolumeIndicatorsChart ticker="UNKNOWN" range="1y" errorSurfacedBySibling />,
    )

    await waitFor(() =>
      expect(
        screen.queryByText('Loading volume indicator history for UNKNOWN...'),
      ).not.toBeInTheDocument(),
    )
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.queryByTestId('volume-indicators-chart-canvas')).not.toBeInTheDocument()
  })

  it('does not fetch or render when disabled (weekly interval upstream), showing an explanatory message instead', async () => {
    let requestCount = 0
    server.use(
      http.get('/api/stocks/:ticker/indicators', () => {
        requestCount += 1
        return HttpResponse.json(indicatorPoints)
      }),
    )

    renderWithProviders(
      <VolumeIndicatorsChart ticker="AAPL" range="1y" enabled={false} />,
    )

    expect(
      screen.getByText(
        'Volume indicators (OBV, A/D) are only available for the Daily interval.',
      ),
    ).toBeInTheDocument()
    expect(screen.queryByTestId('volume-indicators-chart-canvas')).not.toBeInTheDocument()
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
      <VolumeIndicatorsChart ticker="AAPL" range="1y" />,
    )

    await waitFor(() =>
      expect(screen.getByTestId('volume-indicators-chart-canvas')).toBeInTheDocument(),
    )
    expect(lastRequestedRange).toBe('1y')
    expect(createChartMock).toHaveBeenCalledTimes(1)

    rerender(<VolumeIndicatorsChart ticker="AAPL" range="3m" />)

    await waitFor(() => expect(lastRequestedRange).toBe('3m'))
    await waitFor(() => expect(createChartMock).toHaveBeenCalledTimes(2))
    expect(removeMock).toHaveBeenCalledTimes(1)
  })

  it('shows OBV/A-D legend rows with MetricHelp affordances once the chart resolves', async () => {
    mockIndicators(indicatorPoints)

    renderWithProviders(<VolumeIndicatorsChart ticker="AAPL" range="1y" />)

    await waitFor(() =>
      expect(screen.getByTestId('volume-indicators-chart-canvas')).toBeInTheDocument(),
    )

    expect(screen.getByText('On-Balance Volume (OBV)')).toBeInTheDocument()
    expect(screen.getByText('Accumulation/Distribution (A/D)')).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'On-Balance Volume (OBV) help' }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Accumulation/Distribution (A/D) help' }),
    ).toBeInTheDocument()
  })

  it('clicking the OBV legend label hides, then re-shows, the OBV series via applyOptions', async () => {
    mockIndicators(indicatorPoints)
    const user = userEvent.setup()

    renderWithProviders(<VolumeIndicatorsChart ticker="AAPL" range="1y" />)

    await waitFor(() =>
      expect(screen.getByTestId('volume-indicators-chart-canvas')).toBeInTheDocument(),
    )
    applyOptionsMock.mockClear()

    const toggle = screen.getByRole('button', {
      name: 'Hide On-Balance Volume (OBV) on the chart',
    })
    expect(toggle).toHaveAttribute('aria-pressed', 'true')

    await user.click(toggle)

    expect(applyOptionsMock).toHaveBeenCalledWith(0, { visible: false })
    expect(
      screen.getByRole('button', { name: 'Show On-Balance Volume (OBV) on the chart' }),
    ).toHaveAttribute('aria-pressed', 'false')

    await user.click(
      screen.getByRole('button', { name: 'Show On-Balance Volume (OBV) on the chart' }),
    )

    expect(applyOptionsMock).toHaveBeenCalledWith(0, { visible: true })
  })

  it('clicking the A/D legend label hides the A/D series only, leaving OBV visible', async () => {
    mockIndicators(indicatorPoints)
    const user = userEvent.setup()

    renderWithProviders(<VolumeIndicatorsChart ticker="AAPL" range="1y" />)

    await waitFor(() =>
      expect(screen.getByTestId('volume-indicators-chart-canvas')).toBeInTheDocument(),
    )
    applyOptionsMock.mockClear()

    await user.click(
      screen.getByRole('button', {
        name: 'Hide Accumulation/Distribution (A/D) on the chart',
      }),
    )

    expect(applyOptionsMock).toHaveBeenCalledWith(1, { visible: false })
    expect(applyOptionsMock).not.toHaveBeenCalledWith(0, { visible: false })
    expect(
      screen.getByRole('button', { name: 'Hide On-Balance Volume (OBV) on the chart' }),
    ).toHaveAttribute('aria-pressed', 'true')

    // The MetricHelp affordance next to the toggled label is unaffected --
    // still opens its own balloon rather than being intercepted by the
    // sibling toggle's click handler.
    await user.click(
      screen.getByRole('button', { name: 'Accumulation/Distribution (A/D) help' }),
    )
    expect(screen.getByText(/A\/D has fallen/)).toBeInTheDocument()
  })

  it('opens the OBV MetricHelp balloon warning the raw number is meaningless and describing the current pattern', async () => {
    mockIndicators(indicatorPoints)
    const user = userEvent.setup()

    renderWithProviders(<VolumeIndicatorsChart ticker="AAPL" range="1y" />)

    await waitFor(() =>
      expect(screen.getByTestId('volume-indicators-chart-canvas')).toBeInTheDocument(),
    )

    await user.click(screen.getByRole('button', { name: 'On-Balance Volume (OBV) help' }))

    expect(screen.getByText(/means nothing on its own/)).toBeInTheDocument()
    // OBV rose from 5000 to 10500 across the two-bar window shown, and the
    // latest bar is its own highest point in that window.
    expect(screen.getByText(/OBV has risen/)).toBeInTheDocument()
    expect(screen.getByText(/at its own highest point/)).toBeInTheDocument()
  })

  it('opens the A/D MetricHelp balloon describing a falling pattern when the latest value is the window low', async () => {
    mockIndicators(indicatorPoints)
    const user = userEvent.setup()

    renderWithProviders(<VolumeIndicatorsChart ticker="AAPL" range="1y" />)

    await waitFor(() =>
      expect(screen.getByTestId('volume-indicators-chart-canvas')).toBeInTheDocument(),
    )

    await user.click(
      screen.getByRole('button', { name: 'Accumulation/Distribution (A/D) help' }),
    )

    // A/D fell from 1200 to 900 across the two-bar window shown, and the
    // latest bar is its own lowest point in that window.
    expect(screen.getByText(/A\/D has fallen/)).toBeInTheDocument()
    expect(screen.getByText(/at its own lowest point/)).toBeInTheDocument()
  })

  // frontend-chart-fullscreen-resize-followups checklist item: the shared
  // `common/ChartFrame` maximize-toggle/drag-resize wiring is already
  // covered generically against a synthetic test double in
  // `ChartFrame.test.tsx`, and against `PriceChart` by one e2e spec case --
  // but nothing previously exercised that THIS component's own wiring
  // (passing `canvasHeight` into its own chart-container `Box`, placing
  // `maximizeToggle` in its own title row) actually works against real
  // component code, not just a manual browser walkthrough.
  describe('ChartFrame maximize/resize wiring (frontend-chart-fullscreen-resize-followups)', () => {
    it('toggles the chart into and out of full screen, keeping the real canvas container visible inside the dialog', async () => {
      mockIndicators(indicatorPoints)
      const user = userEvent.setup()

      renderWithProviders(<VolumeIndicatorsChart ticker="AAPL" range="1y" />)

      await waitFor(() =>
        expect(screen.getByTestId('volume-indicators-chart-canvas')).toBeInTheDocument(),
      )

      await user.click(
        screen.getByRole('button', { name: 'View Volume indicators full screen' }),
      )

      const dialog = screen.getByRole('dialog', { name: 'Volume indicators full screen' })
      expect(within(dialog).getByTestId('volume-indicators-chart-canvas')).toBeInTheDocument()

      await user.click(
        screen.getByRole('button', { name: 'Exit full screen (Volume indicators)' }),
      )

      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
      expect(screen.getByTestId('volume-indicators-chart-canvas')).toBeInTheDocument()
    })

    it('drag-resizes this chart\'s own container height via the resize handle beneath the canvas', async () => {
      mockIndicators(indicatorPoints)

      renderWithProviders(<VolumeIndicatorsChart ticker="AAPL" range="1y" />)

      const canvasContainer = await screen.findByTestId('volume-indicators-chart-canvas')
      expect(canvasContainer).toHaveStyle({ height: '420px' })

      const handle = screen.getByRole('separator', {
        name: 'Resize Volume indicators height',
      })
      fireEvent.pointerDown(handle, { pointerId: 1, clientY: 100 })
      fireEvent.pointerMove(handle, { pointerId: 1, clientY: 250 })
      fireEvent.pointerUp(handle, { pointerId: 1, clientY: 250 })

      expect(canvasContainer).toHaveStyle({ height: '570px' })
    })
  })
})
