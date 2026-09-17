import Box from '@mui/material/Box'
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
        story:
          'Renders the fallback UI when a child throws during render, sized to fill the viewport (the default `fullPage` usage — see main.tsx).',
      },
    },
  },
}

// The `fullPage={false}` usage this component argues for in its own doc
// comment: wrapping just a feature subtree rather than the whole page. The
// surrounding fixed-height Box stands in for that subtree's own layout —
// the fallback must size itself to it, not force a 100vh minHeight the way
// the default (CaughtError) story does.
export const CaughtErrorSubtree: Story = {
  render: (args) => (
    <Box sx={{ border: '1px dashed', borderColor: 'divider', height: 300 }}>
      <AppErrorBoundary {...args} />
    </Box>
  ),
  args: {
    fullPage: false,
    children: <ThrowsOnRender />,
  },
  parameters: {
    docs: {
      description: {
        story:
          'Renders the fallback UI scoped to a smaller feature subtree (`fullPage={false}`): no 100vh minimum height and copy that no longer suggests reloading the whole app.',
      },
    },
  },
}
