import type { Meta, StoryObj } from '@storybook/react-vite'
import ConfidenceGauge from './ConfidenceGauge'

const meta: Meta<typeof ConfidenceGauge> = {
  title: 'Common/ConfidenceGauge',
  component: ConfidenceGauge,
}

export default meta
type Story = StoryObj<typeof ConfidenceGauge>

export const Zero: Story = {
  args: { confidence: 0 },
}

export const Low: Story = {
  args: { confidence: 25 },
}

export const MediumLowerEdge: Story = {
  args: { confidence: 40 },
}

export const MediumUpperEdge: Story = {
  args: { confidence: 70 },
}

export const High: Story = {
  args: { confidence: 85 },
}

export const Full: Story = {
  args: { confidence: 100 },
}
