import { screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { Screens } from '../../../api/stocks'
import { renderWithTheme } from '../../../../tests/renderWithTheme'
import ScreensPanel from './ScreensPanel'

const bullishScreens: Screens = {
  tide: { trend: 'BULLISH', weekly_macd_histogram_slope: 'rising' },
  impulse: 'GREEN',
  wave: { stochastic_k: 24.3, force_index_2ema: -18234.5, state: 'OVERSOLD_PULLBACK' },
  trigger: { fired: true, reference: 'close_above_prior_high' },
}

describe('ScreensPanel', () => {
  it("doesn't nest Impulse's Chip (a <div>) inside a <p>, which React logs as an invalid-DOM-nesting warning", () => {
    // Regression test for frontend-stock-analysis-page-followups.json's
    // DOM-nesting finding: LabeledValue used to always wrap its `children`
    // in `Typography variant="body2"` (renders a `<p>`), and the Impulse
    // section passes it a Chip (renders a `<div>`) — invalid HTML that React
    // warns about via console.error even though nothing crashes today.
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})

    renderWithTheme(<ScreensPanel screens={bullishScreens} />)

    const nestingWarning = errorSpy.mock.calls.find((call) =>
      String(call[0]).includes('cannot be a descendant of'),
    )
    expect(nestingWarning).toBeUndefined()

    errorSpy.mockRestore()
  })

  it('renders Tide, Impulse, Wave, and Trigger sections with humanized labels', () => {
    renderWithTheme(<ScreensPanel screens={bullishScreens} />)

    expect(screen.getByText('Tide (Screen 1)')).toBeInTheDocument()
    expect(screen.getByText('Bullish')).toBeInTheDocument()
    expect(screen.getByText('Rising')).toBeInTheDocument()

    expect(screen.getByText('Impulse System')).toBeInTheDocument()
    expect(screen.getByText('GREEN')).toBeInTheDocument()

    expect(screen.getByText('Wave (Screen 2)')).toBeInTheDocument()
    expect(screen.getByText('24.3 (Oversold)')).toBeInTheDocument()
    expect(screen.getByText('-18,234.5')).toBeInTheDocument()
    expect(screen.getByText('Oversold pullback')).toBeInTheDocument()

    expect(screen.getByText('Trigger (Screen 3)')).toBeInTheDocument()
    expect(screen.getByText('Yes')).toBeInTheDocument()
    expect(screen.getByText('Close above prior high')).toBeInTheDocument()
  })

  it('flags an overbought stochastic reading and a RED impulse / unfired trigger', () => {
    const bearishScreens: Screens = {
      tide: { trend: 'BEARISH', weekly_macd_histogram_slope: 'falling' },
      impulse: 'RED',
      wave: { stochastic_k: 82.1, force_index_2ema: 5000, state: 'OVERBOUGHT_RALLY' },
      trigger: { fired: false, reference: 'no_trigger' },
    }

    renderWithTheme(<ScreensPanel screens={bearishScreens} />)

    expect(screen.getByText('Bearish')).toBeInTheDocument()
    expect(screen.getByText('Falling')).toBeInTheDocument()
    expect(screen.getByText('RED')).toBeInTheDocument()
    expect(screen.getByText('82.1 (Overbought)')).toBeInTheDocument()
    expect(screen.getByText('No')).toBeInTheDocument()
  })

  it('shows a neutral stochastic note and BLUE impulse in the mid-range', () => {
    const neutralScreens: Screens = {
      tide: { trend: 'NEUTRAL', weekly_macd_histogram_slope: 'flat' },
      impulse: 'BLUE',
      wave: { stochastic_k: 50, force_index_2ema: 0, state: 'RANGING' },
      trigger: { fired: false, reference: 'no_trigger' },
    }

    renderWithTheme(<ScreensPanel screens={neutralScreens} />)

    expect(screen.getByText('Neutral')).toBeInTheDocument()
    expect(screen.getByText('BLUE')).toBeInTheDocument()
    expect(screen.getByText('50.0 (Neutral)')).toBeInTheDocument()
    expect(screen.getByText('Ranging')).toBeInTheDocument()
  })

  it('renders a fallback instead of crashing when the API returns null indicator values', () => {
    // The `Screens`/`WaveScreen` generated types declare stochastic_k/force_index_2ema
    // as non-optional `number`, but the backend can legitimately serialize them as JSON
    // `null` when the latest daily bar hasn't settled yet (NaN indicators -> pydantic's
    // ser_json_inf_nan='null'). Simulate that real-world payload shape here regardless
    // of what the generated type claims, per this task's fix.
    const screensWithNullIndicators: Screens = {
      tide: { trend: 'NEUTRAL', weekly_macd_histogram_slope: 'flat' },
      impulse: 'BLUE',
      wave: {
        stochastic_k: null as unknown as number,
        force_index_2ema: null as unknown as number,
        state: 'RANGING',
      },
      trigger: { fired: false, reference: 'no_trigger' },
    }

    expect(() => renderWithTheme(<ScreensPanel screens={screensWithNullIndicators} />)).not.toThrow()

    const stochasticValue = screen.getByText('Stochastic %K').parentElement
    expect(stochasticValue).toHaveTextContent('—')
    expect(stochasticValue).not.toHaveTextContent('Oversold')
    expect(stochasticValue).not.toHaveTextContent('Overbought')
    expect(stochasticValue).not.toHaveTextContent('Neutral')

    const forceIndexValue = screen.getByText('Force Index (2-EMA)').parentElement
    expect(forceIndexValue).toHaveTextContent('—')
  })
})
