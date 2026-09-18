import type { Meta, StoryObj } from '@storybook/react-vite'
import { MemoryRouter } from 'react-router-dom'
import TickerLink from './TickerLink'

const meta: Meta<typeof TickerLink> = {
  title: 'Common/TickerLink',
  component: TickerLink,
  // TickerLink renders a react-router Link, which needs a router context to
  // resolve `to` — every story gets one, matching how every real usage site
  // (PositionsGlanceTable, PositionsTable, RiskPanel, WatchlistTable) is
  // already rendered inside App.tsx's BrowserRouter.
  decorators: [
    (Story) => (
      <MemoryRouter>
        <Story />
      </MemoryRouter>
    ),
  ],
}

export default meta
type Story = StoryObj<typeof TickerLink>

export const Default: Story = {
  args: { ticker: 'AAPL' },
}

export const WithSpecialCharacters: Story = {
  args: { ticker: 'BRK.B' },
}
