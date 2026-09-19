import type { Meta, StoryObj } from '@storybook/react-vite'
import SignedCurrency from './SignedCurrency'

const meta: Meta<typeof SignedCurrency> = {
  title: 'Common/SignedCurrency',
  component: SignedCurrency,
}

export default meta
type Story = StoryObj<typeof SignedCurrency>

export const Positive: Story = {
  args: { value: 201.0 },
}

export const Negative: Story = {
  args: { value: -84.5 },
}

export const Zero: Story = {
  args: { value: 0 },
}
