import { screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { server } from '../../tests/mocks/server'
import { renderWithProviders } from '../../tests/renderWithProviders'
import StockDetailPage from './StockDetailPage'

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

    await waitFor(() => expect(screen.getByTestId('signal-badge')).toHaveTextContent('BUY'))

    expect(screen.getByRole('heading', { name: 'AAPL' })).toBeInTheDocument()
    expect(screen.getByText('As of 2026-09-11')).toBeInTheDocument()
    expect(screen.getByText('72% · High')).toBeInTheDocument()
    expect(screen.getByRole('table', { name: 'Confidence breakdown' })).toBeInTheDocument()

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
        }),
      ),
    )

    renderStockDetail('MSFT')

    await waitFor(() => expect(screen.getByTestId('signal-badge')).toHaveTextContent('SELL'))
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
            wave: { stochastic_k: 50, force_index_2ema: 0, state: 'RANGING' },
            trigger: { fired: false, reference: 'no_trigger' },
          },
          confidence_breakdown: [
            { component: 'tide_alignment', weight: 0.3, score: 0 },
          ],
          indicators: {
            ema_13: 100,
            ema_26: 100,
            macd_histogram: 0,
            bull_power: 0,
            bear_power: 0,
          },
        }),
      ),
    )

    renderStockDetail('GOOG')

    await waitFor(() => expect(screen.getByTestId('signal-badge')).toHaveTextContent('HOLD'))
    expect(screen.getByText('35% · Low')).toBeInTheDocument()
    expect(screen.getByText('BLUE')).toBeInTheDocument()
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
      screen.getByText('Market data provider is currently unavailable. Try again shortly.'),
    ).toBeInTheDocument()
  })
})
