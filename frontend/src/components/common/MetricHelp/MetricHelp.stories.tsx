import type { Meta, StoryObj } from '@storybook/react-vite'
import MetricHelp from './MetricHelp'

const meta: Meta<typeof MetricHelp> = {
  title: 'Common/MetricHelp',
  component: MetricHelp,
}

export default meta
type Story = StoryObj<typeof MetricHelp>

export const DefinitionOnly: Story = {
  args: {
    metricLabel: 'Tide (Screen 1)',
    definition:
      'The long-term trend, evaluated on the weekly chart. Never trade against the tide.',
    elderContext:
      'Determined by the weekly Impulse System color -- weekly EMA(13) direction and weekly MACD-Histogram direction together (docs/Analyse.md §2 Screen 1).',
  },
}

export const WithValueInterpretation: Story = {
  args: {
    metricLabel: 'Stochastic %K',
    definition:
      "Elder-Ray's oscillator counterpart: measures where the close sits within the recent high/low trading range.",
    elderContext:
      'Below 30 is oversold, above 70 is overbought -- used by Screen 2 (the Wave) to time entries against the Tide (docs/Analyse.md §4).',
    valueInterpretation:
      'Currently 36.9 -- in the neutral zone (30-70): neither overbought nor oversold.',
  },
}
