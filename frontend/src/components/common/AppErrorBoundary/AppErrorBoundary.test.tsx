import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import AppErrorBoundary from './AppErrorBoundary'

describe('AppErrorBoundary', () => {
  it('renders its children when nothing throws', () => {
    render(
      <AppErrorBoundary>
        <div>All good</div>
      </AppErrorBoundary>,
    )

    expect(screen.getByText('All good')).toBeInTheDocument()
  })

  it('renders a fallback instead of crashing when a child throws during render', () => {
    // React (and this boundary's own componentDidCatch) log the caught
    // error to the console — expected noise for this test only.
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})

    function ThrowingComponent(): never {
      throw new Error('boom')
    }

    render(
      <AppErrorBoundary>
        <ThrowingComponent />
      </AppErrorBoundary>,
    )

    expect(
      screen.getByRole('heading', { name: /something went wrong/i }),
    ).toBeInTheDocument()
    consoleError.mockRestore()
  })

  it('lets the user retry, clearing the fallback so children render again', async () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})
    // A boolean flag, not a per-call counter: React's development mode
    // replays a throwing render a second time (for a cleaner console
    // stack trace), so a counter-based condition would flip between the
    // two replay calls and mask the throw instead of triggering the
    // boundary consistently.
    let shouldThrow = true
    function Flaky() {
      if (shouldThrow) throw new Error('boom')
      return <div>Recovered</div>
    }

    render(
      <AppErrorBoundary>
        <Flaky />
      </AppErrorBoundary>,
    )
    expect(
      screen.getByRole('heading', { name: /something went wrong/i }),
    ).toBeInTheDocument()

    shouldThrow = false
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: /try again/i }))

    expect(await screen.findByText('Recovered')).toBeInTheDocument()
    consoleError.mockRestore()
  })
})
