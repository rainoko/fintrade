import type { Meta, StoryObj } from '@storybook/react-vite'
import PercentChange from './PercentChange'

const meta: Meta<typeof PercentChange> = {
  title: 'Common/PercentChange',
  component: PercentChange,
}

export default meta
type Story = StoryObj<typeof PercentChange>

export const Positive: Story = {
  args: { value: 3.2 },
}

export const Negative: Story = {
  args: { value: -1.5 },
}

export const Zero: Story = {
  args: { value: 0 },
}
