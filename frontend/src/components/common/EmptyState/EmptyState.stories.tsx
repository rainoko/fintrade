import Button from '@mui/material/Button'
import type { Meta, StoryObj } from '@storybook/react-vite'
import EmptyState from './EmptyState'

const meta: Meta<typeof EmptyState> = {
  title: 'Common/EmptyState',
  component: EmptyState,
}

export default meta
type Story = StoryObj<typeof EmptyState>

export const Basic: Story = {
  args: {
    message: 'No positions yet.',
  },
}

export const WithAction: Story = {
  args: {
    message: 'No positions yet.',
    action: <Button variant="outlined">Add Position</Button>,
  },
}
