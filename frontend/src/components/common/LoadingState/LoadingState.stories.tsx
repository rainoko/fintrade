import type { Meta, StoryObj } from '@storybook/react-vite'
import LoadingState from './LoadingState'

const meta: Meta<typeof LoadingState> = {
  title: 'Common/LoadingState',
  component: LoadingState,
}

export default meta
type Story = StoryObj<typeof LoadingState>

export const SpinnerOnly: Story = {
  args: {},
}

export const WithMessage: Story = {
  args: {
    message: 'Loading portfolio...',
  },
}
