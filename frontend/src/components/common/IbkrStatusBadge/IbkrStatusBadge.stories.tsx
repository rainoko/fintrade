import type { Meta, StoryObj } from '@storybook/react-vite'
import IbkrStatusBadge from './IbkrStatusBadge'

const meta: Meta<typeof IbkrStatusBadge> = {
  title: 'Common/IbkrStatusBadge',
  component: IbkrStatusBadge,
}

export default meta
type Story = StoryObj<typeof IbkrStatusBadge>

export const Disabled: Story = {
  args: { state: 'disabled' },
}

export const Available: Story = {
  args: { state: 'available' },
}

export const GatewayUnreachable: Story = {
  args: {
    state: 'gateway_unreachable',
    detail: 'IBKR gateway request to /iserver/auth/status failed',
  },
}

export const NotAuthenticated: Story = {
  args: { state: 'not_authenticated', detail: 'please log in' },
}
