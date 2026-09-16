import type { Meta, StoryObj } from '@storybook/react-vite'
import { ApiError } from '../../../api/client'
import ErrorState from './ErrorState'

const meta: Meta<typeof ErrorState> = {
  title: 'Common/ErrorState',
  component: ErrorState,
}

export default meta
type Story = StoryObj<typeof ErrorState>

export const NotFound404: Story = {
  args: {
    error: new ApiError(404, "Ticker 'ZZZZ' not found"),
  },
}

export const InsufficientHistory422: Story = {
  args: {
    error: new ApiError(
      422,
      'Insufficient history to compute weekly indicators (need at least 26 weeks)',
    ),
  },
}

export const ProviderUnavailable503: Story = {
  args: {
    error: new ApiError(
      503,
      'Market data provider unavailable. Please try again shortly.',
    ),
  },
}

export const NetworkFailure: Story = {
  args: {
    error: new ApiError(
      0,
      'Unable to reach the API. Check your connection and try again.',
    ),
  },
}
