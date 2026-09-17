import type { Meta, StoryObj } from '@storybook/react-vite'
import RiskPercent from './RiskPercent'

const meta: Meta<typeof RiskPercent> = {
  title: 'Common/RiskPercent',
  component: RiskPercent,
}

export default meta
type Story = StoryObj<typeof RiskPercent>

export const WithinLimit: Story = {
  args: { value: 1.4 },
}

export const Breached: Story = {
  args: { value: 5.0, breached: true },
}
