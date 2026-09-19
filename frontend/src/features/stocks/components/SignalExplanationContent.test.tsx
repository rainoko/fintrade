import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { Screens } from '../../../api/stocks'
import { renderWithTheme } from '../../../../tests/renderWithTheme'
import SignalExplanationContent from './SignalExplanationContent'

const waveNeverShowedScreens: Screens = {
  tide: { trend: 'BULLISH', weekly_macd_histogram_slope: 'rising' },
  impulse: 'RED',
  wave: {
    stochastic_k: 45.0,
    force_index_2ema: 10.0,
    state: 'NO_WAVE',
    showed_pullback_in_lookback: false,
    showed_rally_in_lookback: false,
  },
  trigger: { fired: false, reference: 'not_applicable' },
}

describe('SignalExplanationContent', () => {
  it('renders the headline and one list item per Triple Screen condition', () => {
    renderWithTheme(
      <SignalExplanationContent signal="HOLD" screens={waveNeverShowedScreens} />,
    )

    expect(
      screen.getByRole('list', { name: 'Signal condition breakdown' }),
    ).toBeInTheDocument()
    expect(screen.getByText('Tide direction (Screen 1)')).toBeInTheDocument()
    expect(screen.getByText('Impulse gate')).toBeInTheDocument()
    expect(screen.getByText('Wave pullback/rally (Screen 2)')).toBeInTheDocument()
    expect(screen.getByText('Trigger fired (Screen 3)')).toBeInTheDocument()

    // Impulse blocks a fresh BUY here (RED) -- its detail line is rendered.
    expect(screen.getByText(/blocks any fresh BUY/)).toBeInTheDocument()
    // Wave's true 5-day lookback state is now known definitively --
    // showed_pullback_in_lookback: false resolves to a real not-met claim,
    // not the old ambiguous caveat.
    expect(
      screen.getByText(/has not shown a qualifying oversold pullback/),
    ).toBeInTheDocument()
  })
})
