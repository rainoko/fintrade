import type { Meta, StoryObj } from '@storybook/react-vite'
import SignalBadge from './SignalBadge'

const meta: Meta<typeof SignalBadge> = {
  title: 'Common/SignalBadge',
  component: SignalBadge,
}

export default meta
type Story = StoryObj<typeof SignalBadge>

export const Buy: Story = {
  args: { signal: 'BUY' },
}

export const Sell: Story = {
  args: { signal: 'SELL' },
}

export const Hold: Story = {
  args: { signal: 'HOLD' },
}
