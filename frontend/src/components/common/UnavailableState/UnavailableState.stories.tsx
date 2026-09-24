import type { Meta, StoryObj } from '@storybook/react-vite'
import UnavailableState from './UnavailableState'

const meta: Meta<typeof UnavailableState> = {
  title: 'Common/UnavailableState',
  component: UnavailableState,
}

export default meta
type Story = StoryObj<typeof UnavailableState>

export const Disabled: Story = {
  args: {
    heading: 'Scanner unavailable',
    message: 'IBKR integration is disabled (FINTRADE_IBKR_ENABLED is not set).',
  },
}

export const GatewayUnreachable: Story = {
  args: {
    heading: 'Scanner unavailable',
    message: 'The IBKR Client Portal Gateway is not reachable right now.',
  },
}

export const HeadingOnly: Story = {
  args: {
    heading: 'Scanner unavailable',
  },
}
