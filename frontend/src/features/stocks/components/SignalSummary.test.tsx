import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { ConfidenceBreakdownItem, Screens } from '../../../api/stocks'
import { renderWithTheme } from '../../../../tests/renderWithTheme'
import SignalSummary from './SignalSummary'

const breakdown: ConfidenceBreakdownItem[] = [
  { component: 'tide_alignment', weight: 0.3, score: 1.0 },
  { component: 'impulse_gate', weight: 0.2, score: 1.0 },
  { component: 'oscillator_extremity', weight: 0.25, score: 0.6 },
  { component: 'elder_ray_confirmation', weight: 0.15, score: 0.5 },
  { component: 'volume_confirmation', weight: 0.1, score: 1.0 },
]

const buyScreens: Screens = {
  tide: { trend: 'BULLISH', weekly_macd_histogram_slope: 'rising' },
  impulse: 'GREEN',
  wave: { stochastic_k: 24.3, force_index_2ema: -18234.5, state: 'OVERSOLD_PULLBACK' },
  trigger: { fired: true, reference: 'close_above_prior_high' },
}

const sellScreens: Screens = {
  tide: { trend: 'BEARISH', weekly_macd_histogram_slope: 'falling' },
  impulse: 'RED',
  wave: { stochastic_k: 78.1, force_index_2ema: 15234.2, state: 'OVERBOUGHT_RALLY' },
  trigger: { fired: true, reference: 'close_below_prior_low' },
}

const holdNeutralScreens: Screens = {
  tide: { trend: 'NEUTRAL', weekly_macd_histogram_slope: 'flat' },
  impulse: 'BLUE',
  wave: { stochastic_k: 50.0, force_index_2ema: 100.0, state: 'NO_WAVE' },
  trigger: { fired: false, reference: 'not_applicable' },
}

const holdMissingWaveScreens: Screens = {
  tide: { trend: 'BULLISH', weekly_macd_histogram_slope: 'rising' },
  impulse: 'GREEN',
  wave: { stochastic_k: 55.0, force_index_2ema: 200.0, state: 'NO_WAVE' },
  trigger: { fired: true, reference: 'close_above_prior_high' },
}

describe('SignalSummary', () => {
  it('renders a BUY signal, confidence gauge, and the breakdown table', () => {
    renderWithTheme(
      <SignalSummary
        signal="BUY"
        confidence={72}
        confidenceBand="High"
        confidenceBreakdown={breakdown}
        screens={buyScreens}
      />,
    )

    expect(screen.getByTestId('signal-badge')).toHaveTextContent('BUY')
    expect(screen.getByText('72% · High')).toBeInTheDocument()

    expect(
      screen.getByRole('table', { name: 'Confidence breakdown' }),
    ).toBeInTheDocument()
    expect(screen.getByText('Tide alignment (Screen 1)')).toBeInTheDocument()
    expect(screen.getByText('Impulse gate')).toBeInTheDocument()
    expect(screen.getByText('Oscillator extremity (Screen 2)')).toBeInTheDocument()
    expect(screen.getByText('Elder-Ray confirmation')).toBeInTheDocument()
    expect(screen.getByText('Volume confirmation')).toBeInTheDocument()
    expect(screen.getByText('30%')).toBeInTheDocument()
    expect(screen.getAllByText('100%')).toHaveLength(3)
  })

  it('renders a SELL signal at Low confidence', () => {
    renderWithTheme(
      <SignalSummary
        signal="SELL"
        confidence={22}
        confidenceBand="Low"
        confidenceBreakdown={[{ component: 'tide_alignment', weight: 0.3, score: 0 }]}
        screens={sellScreens}
      />,
    )

    expect(screen.getByTestId('signal-badge')).toHaveTextContent('SELL')
    expect(screen.getByText('22% · Low')).toBeInTheDocument()
  })

  it("passes the API's confidence_band through to ConfidenceGauge instead of re-deriving it", () => {
    // confidence=50 would locally re-derive to Medium (confidenceBand.ts's own
    // 40-70 rule); passing band="High" here proves SignalSummary forwards the
    // API's own confidence_band rather than letting ConfidenceGauge recompute
    // it, so the two can't silently disagree.
    renderWithTheme(
      <SignalSummary
        signal="HOLD"
        confidence={50}
        confidenceBand="High"
        confidenceBreakdown={[{ component: 'tide_alignment', weight: 0.3, score: 0.5 }]}
        screens={holdNeutralScreens}
      />,
    )

    expect(screen.getByText('50% · High')).toBeInTheDocument()
  })

  it('humanizes an unrecognized confidence_breakdown component name', () => {
    renderWithTheme(
      <SignalSummary
        signal="HOLD"
        confidence={50}
        confidenceBand="Medium"
        confidenceBreakdown={[{ component: 'future_component', weight: 0.5, score: 0.5 }]}
        screens={holdNeutralScreens}
      />,
    )

    expect(screen.getByTestId('signal-badge')).toHaveTextContent('HOLD')
    expect(screen.getByText('Future component')).toBeInTheDocument()
  })

  it('shows the empty-breakdown state when confidence_breakdown is empty', () => {
    renderWithTheme(
      <SignalSummary
        signal="HOLD"
        confidence={50}
        confidenceBand="Medium"
        confidenceBreakdown={[]}
        screens={holdNeutralScreens}
      />,
    )

    expect(screen.getByText('No confidence breakdown available.')).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('clicking a BUY signal opens a balloon explaining every condition as met', async () => {
    const user = userEvent.setup()
    renderWithTheme(
      <SignalSummary
        signal="BUY"
        confidence={72}
        confidenceBand="High"
        confidenceBreakdown={breakdown}
        screens={buyScreens}
      />,
    )

    await user.click(screen.getByRole('button', { name: 'Why BUY?' }))

    expect(
      screen.getByText(/BUY: every Triple Screen condition lined up/),
    ).toBeInTheDocument()
    expect(screen.getByText(/Wave shows an oversold pullback today/)).toBeInTheDocument()
  })

  it('clicking a SELL signal opens a balloon explaining every condition as met', async () => {
    const user = userEvent.setup()
    renderWithTheme(
      <SignalSummary
        signal="SELL"
        confidence={65}
        confidenceBand="Medium"
        confidenceBreakdown={breakdown}
        screens={sellScreens}
      />,
    )

    await user.click(screen.getByRole('button', { name: 'Why SELL?' }))

    expect(
      screen.getByText(/SELL: every Triple Screen condition lined up/),
    ).toBeInTheDocument()
    expect(screen.getByText(/Wave shows an overbought rally today/)).toBeInTheDocument()
  })

  it('clicking a Neutral-tide HOLD signal names Tide as the blocking condition, not a generic message', async () => {
    const user = userEvent.setup()
    renderWithTheme(
      <SignalSummary
        signal="HOLD"
        confidence={0}
        confidenceBand="Low"
        confidenceBreakdown={[]}
        screens={holdNeutralScreens}
      />,
    )

    await user.click(screen.getByRole('button', { name: 'Why HOLD?' }))

    expect(screen.getAllByText(/Tide is Neutral/).length).toBeGreaterThan(0)
  })

  it('clicking a directional-tide HOLD signal missing only Wave names Wave specifically, not Tide', async () => {
    const user = userEvent.setup()
    renderWithTheme(
      <SignalSummary
        signal="HOLD"
        confidence={0}
        confidenceBand="Low"
        confidenceBreakdown={[]}
        screens={holdMissingWaveScreens}
      />,
    )

    await user.click(screen.getByRole('button', { name: 'Why HOLD?' }))

    expect(
      screen.getByText(/missing: Wave pullback\/rally \(Screen 2\)/),
    ).toBeInTheDocument()
    // Proves the two HOLD cases render genuinely different explanations
    // rather than a templated "conditions not met" message either way.
    expect(screen.queryByText(/Tide is Neutral/)).not.toBeInTheDocument()
  })

  it('wires the right MetricHelp content to the Signal/Confidence icons and each breakdown row, distinct from the badge’s own "why" balloon', async () => {
    const user = userEvent.setup()
    renderWithTheme(
      <SignalSummary
        signal="BUY"
        confidence={72}
        confidenceBand="High"
        confidenceBreakdown={breakdown}
        screens={buyScreens}
      />,
    )

    // Generic Signal help (definitional), distinct from "Why BUY?"'s causal explanation.
    await user.click(screen.getByRole('button', { name: 'Signal help' }))
    expect(
      screen.getByText(/Currently BUY -- every Triple Screen condition lined up/),
    ).toBeInTheDocument()
    await user.keyboard('{Escape}')

    // Confidence help.
    await user.click(screen.getByRole('button', { name: 'Confidence help' }))
    expect(screen.getByText('Currently 72% -- High confidence.')).toBeInTheDocument()
    await user.keyboard('{Escape}')

    // The tide_alignment breakdown row's own help, not a different component's.
    await user.click(
      screen.getByRole('button', { name: 'Tide alignment (Screen 1) help' }),
    )
    expect(
      screen.getByText(
        /scored 100% at a 30% weight -- contributing 30 of the 100 possible/,
      ),
    ).toBeInTheDocument()
    expect(screen.queryByText(/Currently BUY/)).not.toBeInTheDocument()
  })
})
