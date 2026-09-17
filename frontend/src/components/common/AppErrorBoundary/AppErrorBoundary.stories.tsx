import type { Meta, StoryObj } from '@storybook/react-vite'
import AppErrorBoundary from './AppErrorBoundary'

const meta: Meta<typeof AppErrorBoundary> = {
  title: 'Common/AppErrorBoundary',
  component: AppErrorBoundary,
}

export default meta
type Story = StoryObj<typeof AppErrorBoundary>

export const RendersChildren: Story = {
  args: {
    children: <div>Everything is fine — no error was thrown.</div>,
  },
}

// A component that throws during render, purely to exercise the boundary's
// fallback UI in isolation (per Frontend.md §4 — a common/ component's
// story must cover its meaningful states, and "catches a render crash" is
// this component's entire reason to exist).
function ThrowsOnRender(): never {
  throw new Error('Story-triggered render error')
}

export const CaughtError: Story = {
  args: {
    children: <ThrowsOnRender />,
  },
  parameters: {
    // React and this boundary's own componentDidCatch both log the caught
    // error to the console by design (see AppErrorBoundary.tsx) — expected
    // noise for this story, not a real failure.
    docs: {
      description: {
        story: 'Renders the fallback UI when a child throws during render.',
      },
    },
  },
}
