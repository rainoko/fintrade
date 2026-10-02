import Box from '@mui/material/Box'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import type { Meta, StoryObj } from '@storybook/react-vite'
import ChartFrame from './ChartFrame'

const meta: Meta<typeof ChartFrame> = {
  title: 'Common/ChartFrame',
  component: ChartFrame,
}

export default meta
type Story = StoryObj<typeof ChartFrame>

/**
 * Stand-in "chart canvas" -- a plain gradient `Box` whose height mirrors
 * whatever `ChartFrame` reports via `canvasHeight`, since a real Lightweight
 * Charts instance needs a `<canvas>` 2D context Storybook's own test
 * environment doesn't meaningfully render (same reasoning the
 * `PriceChart`/`OscillatorChart`/etc. unit tests mock `lightweight-charts`
 * for).
 */
export const Default: Story = {
  args: {
    label: 'Price chart',
    defaultHeight: 320,
  },
  render: (args) => (
    <ChartFrame {...args}>
      {({ canvasHeight, maximizeToggle, resizeHandle }) => (
        <Stack spacing={1}>
          <Stack direction="row" sx={{ alignItems: 'center', justifyContent: 'space-between' }}>
            <Typography variant="subtitle2" color="text.secondary">
              {args.label}
            </Typography>
            {maximizeToggle}
          </Stack>
          <Box
            data-testid="story-canvas"
            sx={{
              width: '100%',
              height: canvasHeight,
              background:
                'repeating-linear-gradient(45deg, #1976d2 0, #1976d2 10px, #90caf9 10px, #90caf9 20px)',
              borderRadius: 1,
            }}
          />
          {resizeHandle}
        </Stack>
      )}
    </ChartFrame>
  ),
}

/** A taller default, matching `OscillatorChart`/`VolumeIndicatorsChart`/
 * `TrendStrengthChart`'s shared 420px `CHART_HEIGHT`. */
export const TallerDefault: Story = {
  args: {
    label: 'Oscillators',
    defaultHeight: 420,
  },
  render: Default.render,
}
