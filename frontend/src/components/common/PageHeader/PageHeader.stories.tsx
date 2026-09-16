import Button from '@mui/material/Button'
import type { Meta, StoryObj } from '@storybook/react-vite'
import PageHeader from './PageHeader'

const meta: Meta<typeof PageHeader> = {
  title: 'Common/PageHeader',
  component: PageHeader,
}

export default meta
type Story = StoryObj<typeof PageHeader>

export const WithoutAction: Story = {
  args: {
    title: 'Dashboard',
  },
}

export const WithAction: Story = {
  args: {
    title: 'Portfolio',
    action: <Button variant="contained">Add Position</Button>,
  },
}
