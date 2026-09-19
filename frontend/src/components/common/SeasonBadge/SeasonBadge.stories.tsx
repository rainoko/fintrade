import type { Meta, StoryObj } from '@storybook/react-vite'
import SeasonBadge from './SeasonBadge'

const meta: Meta<typeof SeasonBadge> = {
  title: 'Common/SeasonBadge',
  component: SeasonBadge,
}

export default meta
type Story = StoryObj<typeof SeasonBadge>

export const Spring: Story = {
  args: { season: 'Spring' },
}

export const Summer: Story = {
  args: { season: 'Summer' },
}

export const Autumn: Story = {
  args: { season: 'Autumn' },
}

export const Winter: Story = {
  args: { season: 'Winter' },
}
