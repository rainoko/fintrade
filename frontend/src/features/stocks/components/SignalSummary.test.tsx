import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { ConfidenceBreakdownItem } from '../../../api/stocks'
import { renderWithTheme } from '../../../../tests/renderWithTheme'
import SignalSummary from './SignalSummary'

const breakdown: ConfidenceBreakdownItem[] = [
  { component: 'tide_alignment', weight: 0.3, score: 1.0 },
  { component: 'impulse_gate', weight: 0.2, score: 1.0 },
  { component: 'oscillator_extremity', weight: 0.25, score: 0.6 },
  { component: 'elder_ray_confirmation', weight: 0.15, score: 0.5 },
  { component: 'volume_confirmation', weight: 0.1, score: 1.0 },
]

describe('SignalSummary', () => {
  it('renders a BUY signal, confidence gauge, and the breakdown table', () => {
    renderWithTheme(
      <SignalSummary
        signal="BUY"
        confidence={72}
        confidenceBand="High"
        confidenceBreakdown={breakdown}
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
      />,
    )

    expect(screen.getByText('No confidence breakdown available.')).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })
})
