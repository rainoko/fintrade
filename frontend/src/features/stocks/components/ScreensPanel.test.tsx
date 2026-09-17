import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
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
})
