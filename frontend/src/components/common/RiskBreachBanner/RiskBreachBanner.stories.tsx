import type { Meta, StoryObj } from '@storybook/react-vite'
import RiskBreachBanner from './RiskBreachBanner'

const meta: Meta<typeof RiskBreachBanner> = {
  title: 'Common/RiskBreachBanner',
  component: RiskBreachBanner,
}

export default meta
type Story = StoryObj<typeof RiskBreachBanner>

export const PortfolioPageWording: Story = {
  args: {
    message:
      '6% rule breached — total open risk is 7.20% of equity (limit 6%). Consider trimming or closing your highest-risk position(s) first.',
  },
}

export const DashboardWording: Story = {
  args: {
    message:
      '6% rule breached — total open risk is 7.20% of equity (limit 6%). See the Portfolio page for details.',
  },
}
