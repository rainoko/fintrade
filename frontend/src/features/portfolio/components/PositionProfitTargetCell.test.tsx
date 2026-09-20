import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import type { AnalysisResponse } from '../../../api/stocks'
import { server } from '../../../../tests/mocks/server'
import { renderWithProviders } from '../../../../tests/renderWithProviders'
import PositionProfitTargetCell from './PositionProfitTargetCell'

function mockAnalysis(ticker: string, response: Partial<AnalysisResponse>) {
  server.use(
    http.get(`/api/stocks/${ticker}/analysis`, () =>
      HttpResponse.json({
        ticker,
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
        profit_target: null,
        ...response,
      }),
    ),
  )
}

describe('PositionProfitTargetCell', () => {
  it('shows an explained em dash without fetching when the position signal is not BUY', () => {
    let fetched = false
    server.use(
      http.get('/api/stocks/MSFT/analysis', () => {
        fetched = true
        return HttpResponse.json({ detail: 'should not be called' }, { status: 500 })
      }),
    )

    renderWithProviders(<PositionProfitTargetCell ticker="MSFT" signal="HOLD" />)

    expect(screen.getByText('—')).toBeInTheDocument()
    expect(fetched).toBe(false)
  })

  it('shows an explained em dash when the position signal could not be computed at all', () => {
    renderWithProviders(<PositionProfitTargetCell ticker="ZZZZ" signal={null} />)

    expect(screen.getByText('—')).toBeInTheDocument()
  })

  it('shows a loading placeholder, then the target price and a passing reward:risk badge for a BUY position', async () => {
    mockAnalysis('AAPL', {
      profit_target: {
        price: 245.0,
        source: 'channel',
        distance_to_stop: 9.3,
        distance_to_target: 18.6,
        reward_risk_ratio: 2.0,
        meets_minimum_reward_risk: true,
      },
    })

    renderWithProviders(<PositionProfitTargetCell ticker="AAPL" signal="BUY" />)

    expect(screen.getByText('Checking…')).toBeInTheDocument()

    await waitFor(() => expect(screen.getByText('$245.00')).toBeInTheDocument())
    expect(screen.getByText('2.0:1')).toBeInTheDocument()
    expect(screen.queryByLabelText('Below the 2:1 minimum')).not.toBeInTheDocument()
  })

  it('visually flags a BUY position whose reward:risk ratio fails the 2:1 rule', async () => {
    mockAnalysis('TSLA', {
      profit_target: {
        price: 235.0,
        source: 'support_resistance',
        distance_to_stop: 9.3,
        distance_to_target: 8.6,
        reward_risk_ratio: 0.9,
        meets_minimum_reward_risk: false,
      },
    })

    renderWithProviders(<PositionProfitTargetCell ticker="TSLA" signal="BUY" />)

    await waitFor(() => expect(screen.getByText('$235.00')).toBeInTheDocument())
    expect(screen.getByText('0.9:1')).toBeInTheDocument()
    expect(screen.getByLabelText('Below the 2:1 minimum')).toBeInTheDocument()
  })

  it('renders "n/a" for the ratio when the API omits reward_risk_ratio entirely', async () => {
    mockAnalysis('AMD', {
      profit_target: {
        price: 100.0,
        source: 'channel',
        distance_to_stop: 5.0,
        distance_to_target: 4.0,
        meets_minimum_reward_risk: false,
        // reward_risk_ratio intentionally omitted -- an optional field the
        // backend can leave unset, distinct from an explicit `null`.
      } as AnalysisResponse['profit_target'],
    })

    renderWithProviders(<PositionProfitTargetCell ticker="AMD" signal="BUY" />)

    await waitFor(() => expect(screen.getByText('$100.00')).toBeInTheDocument())
    expect(screen.getByText('n/a')).toBeInTheDocument()
  })

  it('shows an explained em dash for a BUY position with no current target candidate', async () => {
    mockAnalysis('NVDA', { profit_target: null })

    renderWithProviders(<PositionProfitTargetCell ticker="NVDA" signal="BUY" />)

    await waitFor(() => expect(screen.getByText('—')).toBeInTheDocument())
  })

  it('shows an explained em dash when the analysis fetch itself fails', async () => {
    server.use(
      http.get('/api/stocks/BADFETCH/analysis', () =>
        HttpResponse.json({ detail: 'boom' }, { status: 500 }),
      ),
    )

    renderWithProviders(<PositionProfitTargetCell ticker="BADFETCH" signal="BUY" />)

    await waitFor(() => expect(screen.getByText('—')).toBeInTheDocument())
  })

  it('opens MetricHelp with the current target/ratio interpretation', async () => {
    mockAnalysis('AAPL', {
      profit_target: {
        price: 245.0,
        source: 'channel',
        distance_to_stop: 9.3,
        distance_to_target: 18.6,
        reward_risk_ratio: 2.0,
        meets_minimum_reward_risk: true,
      },
    })
    const user = userEvent.setup()

    renderWithProviders(<PositionProfitTargetCell ticker="AAPL" signal="BUY" />)

    await waitFor(() => expect(screen.getByText('$245.00')).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: 'Profit Target help' }))
    expect(
      screen.getByText(/Currently 245.00, from the channel\/Tradebill formula/),
    ).toBeInTheDocument()
  })
})
