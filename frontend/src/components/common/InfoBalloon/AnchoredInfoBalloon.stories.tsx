import type { Meta, StoryObj } from '@storybook/react-vite'
import { AnchoredInfoBalloon } from './InfoBalloon'

// `AnchoredInfoBalloon` (frontend-divergence-markers): `InfoBalloon`'s same
// title+content balloon, opened by fixed page coordinates instead of a
// clickable trigger child -- for a trigger that has no DOM element of its
// own to click, such as a chart marker drawn on a `<canvas>` (see
// `PriceChart.tsx`'s/`OscillatorChart.tsx`'s divergence-marker click
// handling for the one real caller today). A separate story file (not
// stories on `InfoBalloon.stories.tsx`'s own default export) since
// Storybook's CSF format only supports one `component`/`meta` per file --
// see this task's `decisions` entry.
const meta: Meta<typeof AnchoredInfoBalloon> = {
  title: 'Common/InfoBalloon/AnchoredInfoBalloon',
  component: AnchoredInfoBalloon,
}

export default meta
type Story = StoryObj<typeof AnchoredInfoBalloon>

// Storybook has no real "click a canvas marker" interaction to trigger
// this with, so this story shows the balloon already open at a fixed
// anchor position.
export const Open: Story = {
  args: {
    open: true,
    anchorPosition: { top: 160, left: 160 },
    onClose: () => {},
    title: 'Divergence',
    ariaLabel: 'Divergence details',
    content:
      'Bullish MACD-Histogram divergence, comparing two successive price swing lows: 2026-08-03 (price 210.50, MACD-Histogram -6.00) vs 2026-08-31 (price 205.20, MACD-Histogram -1.50). MACD-Histogram crossed back through its own zero centerline between the two dates, the required confirmation for a true MACD-Histogram divergence. The two extremes are 20 trading days apart (Kerry Lovvorn’s empirical 20-40-day window). Implies a potential buy setup -- selling momentum is fading even as price makes a new low.',
  },
}

export const Closed: Story = {
  args: {
    ...Open.args,
    open: false,
  },
}
