import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { renderWithTheme } from '../../../../tests/renderWithTheme'
import MetricHelp from './MetricHelp'

describe('MetricHelp', () => {
  it('renders only the question-mark trigger before it is clicked', () => {
    renderWithTheme(
      <MetricHelp
        metricLabel="EMA (13)"
        definition="A 13-period Exponential Moving Average."
        elderContext="Feeds the Tide and Impulse System (docs/Analyse.md §2-3)."
      />,
    )

    expect(screen.getByRole('button', { name: 'EMA (13) help' })).toBeInTheDocument()
    expect(
      screen.queryByText('A 13-period Exponential Moving Average.'),
    ).not.toBeInTheDocument()
  })

  it('opens the balloon with the metric label, definition, and Elder context on click', async () => {
    const user = userEvent.setup()
    renderWithTheme(
      <MetricHelp
        metricLabel="EMA (13)"
        definition="A 13-period Exponential Moving Average."
        elderContext="Feeds the Tide and Impulse System (docs/Analyse.md §2-3)."
      />,
    )

    await user.click(screen.getByRole('button', { name: 'EMA (13) help' }))

    expect(screen.getAllByText('EMA (13)').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText('A 13-period Exponential Moving Average.')).toBeInTheDocument()
    expect(
      screen.getByText('Feeds the Tide and Impulse System (docs/Analyse.md §2-3).'),
    ).toBeInTheDocument()
  })

  it('renders the current-value interpretation when given one', async () => {
    const user = userEvent.setup()
    renderWithTheme(
      <MetricHelp
        metricLabel="Stochastic %K"
        definition="Measures where the close sits within the recent high/low range."
        elderContext="Below 30 is oversold, above 70 is overbought (docs/Analyse.md §4)."
        valueInterpretation="Currently 36.9 -- in the neutral zone (30-70): neither overbought nor oversold."
      />,
    )

    await user.click(screen.getByRole('button', { name: 'Stochastic %K help' }))

    expect(
      screen.getByText(
        'Currently 36.9 -- in the neutral zone (30-70): neither overbought nor oversold.',
      ),
    ).toBeInTheDocument()
  })

  it('omits the current-value line entirely when none is given', async () => {
    const user = userEvent.setup()
    renderWithTheme(
      <MetricHelp
        metricLabel="Tide (Screen 1)"
        definition="The long-term trend, evaluated on the weekly chart."
        elderContext="Never trade against the tide (docs/Analyse.md §2)."
      />,
    )

    await user.click(screen.getByRole('button', { name: 'Tide (Screen 1) help' }))

    // Only the definition + Elder-context lines are present; no third,
    // bold current-value paragraph.
    expect(screen.getAllByText(/./).length).toBeGreaterThan(0)
    expect(screen.queryByText(/Currently/)).not.toBeInTheDocument()
  })
})
