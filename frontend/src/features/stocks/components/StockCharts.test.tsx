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
    addSeries: () => ({ setData: () => {}, createPriceLine: () => ({}) }),
    removeSeries: () => {},
    timeScale: () => ({ fitContent: () => {} }),
    remove: () => {},
  }),
  createSeriesMarkers: () => ({ setMarkers: () => {}, detach: () => {} }),
  CandlestickSeries: 'CandlestickSeries-definition',
  LineSeries: 'LineSeries-definition',
  HistogramSeries: 'HistogramSeries-definition',
  AreaSeries: 'AreaSeries-definition',
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
          'Oscillators (Stochastic %K, Force Index, MACD Histogram) are only available for the Daily interval.',
        ),
      ).toBeInTheDocument(),
    )
    expect(screen.queryByTestId('oscillator-chart-canvas')).not.toBeInTheDocument()

    await user.click(within(intervalGroup).getByRole('button', { name: 'Daily' }))

    await waitFor(() =>
      expect(screen.getByTestId('oscillator-chart-canvas')).toBeInTheDocument(),
    )
  })
})
