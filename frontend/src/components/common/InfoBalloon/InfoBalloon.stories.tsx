import Chip from '@mui/material/Chip'
import type { Meta, StoryObj } from '@storybook/react-vite'
import InfoBalloon from './InfoBalloon'

const meta: Meta<typeof InfoBalloon> = {
  title: 'Common/InfoBalloon',
  component: InfoBalloon,
}

export default meta
type Story = StoryObj<typeof InfoBalloon>

export const ShortText: Story = {
  args: {
    triggerAriaLabel: 'Why BUY?',
    title: 'Why BUY?',
    content: 'Tide, Impulse, Wave, and Trigger all lined up for a fresh BUY.',
    children: <Chip label="BUY" color="success" />,
  },
}

export const RichContent: Story = {
  args: {
    triggerAriaLabel: 'Why HOLD?',
    title: 'Why HOLD?',
    content: (
      <ul style={{ margin: 0, paddingLeft: '1.2em' }}>
        <li>Tide: Bullish (met)</li>
        <li>Impulse: not blocking (met)</li>
        <li>Wave: no qualifying pullback in the last 5 sessions (not met)</li>
        <li>Trigger: not fired (not met)</li>
      </ul>
    ),
    children: <Chip label="HOLD" color="warning" />,
  },
}
