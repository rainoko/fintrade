import HelpOutlineIcon from '@mui/icons-material/HelpOutlineOutlined'
import type { Meta, StoryObj } from '@storybook/react-vite'
import StatCard from './StatCard'

const meta: Meta<typeof StatCard> = {
  title: 'Common/StatCard',
  component: StatCard,
}

export default meta
type Story = StoryObj<typeof StatCard>

export const NoDelta: Story = {
  args: {
    label: 'Total Equity',
    value: '$10,000.00',
  },
}

export const PositiveDelta: Story = {
  args: {
    label: 'Total Equity',
    value: '$10,320.00',
    delta: { text: '+3.20%', direction: 'positive' },
  },
}

export const NegativeDelta: Story = {
  args: {
    label: 'Total Open Risk',
    value: '6.50%',
    delta: { text: '-0.80%', direction: 'negative' },
  },
}

export const NeutralDelta: Story = {
  args: {
    label: 'Open Positions',
    value: '4',
    delta: { text: 'no change', direction: 'neutral' },
  },
}

export const WithCornerContent: Story = {
  args: {
    label: 'EMA (13)',
    value: '226.40',
    corner: <HelpOutlineIcon fontSize="small" color="action" />,
  },
}
