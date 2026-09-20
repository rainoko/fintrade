import type { Meta, StoryObj } from '@storybook/react-vite'
import RewardRiskBadge from './RewardRiskBadge'

const meta: Meta<typeof RewardRiskBadge> = {
  title: 'Common/RewardRiskBadge',
  component: RewardRiskBadge,
}

export default meta
type Story = StoryObj<typeof RewardRiskBadge>

export const MeetsMinimum: Story = {
  args: { ratio: 2.4, meetsMinimum: true },
}

export const FailsMinimum: Story = {
  args: { ratio: 1.3, meetsMinimum: false },
}

export const Undefined: Story = {
  args: { ratio: null, meetsMinimum: false },
}
