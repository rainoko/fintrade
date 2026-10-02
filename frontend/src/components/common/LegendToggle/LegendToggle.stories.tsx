import Box from '@mui/material/Box'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import type { Meta, StoryObj } from '@storybook/react-vite'
import { useState } from 'react'
import LegendToggle from './LegendToggle'

const meta: Meta<typeof LegendToggle> = {
  title: 'Common/LegendToggle',
  component: LegendToggle,
}

export default meta
type Story = StoryObj<typeof LegendToggle>

function ExampleRow({ initiallyActive }: { initiallyActive: boolean }) {
  const [active, setActive] = useState(initiallyActive)
  return (
    <LegendToggle active={active} label="Fibonacci Retracement" onToggle={() => setActive((v) => !v)}>
      <Box
        sx={{ width: 14, height: 0, borderTop: '2px dotted', borderColor: 'warning.main' }}
      />
      <Typography variant="caption" color="text.secondary">
        Fibonacci Retracement
      </Typography>
    </LegendToggle>
  )
}

export const Active: Story = {
  render: () => <ExampleRow initiallyActive />,
}

export const Inactive: Story = {
  render: () => <ExampleRow initiallyActive={false} />,
}

export const MultipleRows: Story = {
  render: () => (
    <Stack direction="row" spacing={3}>
      <ExampleRow initiallyActive />
      <ExampleRow initiallyActive={false} />
    </Stack>
  ),
}
