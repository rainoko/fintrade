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

  it('defaults to full-page-sized fallback chrome (100vh, whole-app copy)', () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})

    function ThrowingComponent(): never {
      throw new Error('boom')
    }

    render(
      <AppErrorBoundary>
        <ThrowingComponent />
      </AppErrorBoundary>,
    )

    const heading = screen.getByRole('heading', { name: /something went wrong/i })
    // The Box carrying minHeight is the heading's nearest flex-column
    // ancestor (see AppErrorBoundary.tsx's render()). jsdom resolves a
    // `100vh` sx value against `window.innerHeight` at computed-style time
    // (rather than keeping the literal string `100vh`), so assert against
    // that resolved pixel value instead of the CSS unit itself.
    expect(getComputedStyle(heading.parentElement!).minHeight).toBe(
      `${window.innerHeight}px`,
    )
    expect(
      screen.getByText(/rendering this page\. try again, or reload the app\./i),
    ).toBeInTheDocument()
    consoleError.mockRestore()
  })

  it('sizes the fallback to its subtree (not the viewport) and drops the whole-app copy when fullPage is false', () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})

    function ThrowingComponent(): never {
      throw new Error('boom')
    }

    render(
      <AppErrorBoundary fullPage={false}>
        <ThrowingComponent />
      </AppErrorBoundary>,
    )

    const heading = screen.getByRole('heading', { name: /something went wrong/i })
    expect(getComputedStyle(heading.parentElement!).minHeight).not.toBe(
      `${window.innerHeight}px`,
    )
    expect(getComputedStyle(heading.parentElement!).minHeight).toBe('200px')
    expect(
      screen.getByText(/rendering this section\. try again\./i),
    ).toBeInTheDocument()
    expect(screen.queryByText(/reload the app/i)).not.toBeInTheDocument()
    consoleError.mockRestore()
  })

  it('lets a custom message override the default copy regardless of fullPage', () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})

    function ThrowingComponent(): never {
      throw new Error('boom')
    }

    render(
      <AppErrorBoundary message="Custom fallback copy">
        <ThrowingComponent />
      </AppErrorBoundary>,
    )

    expect(screen.getByText('Custom fallback copy')).toBeInTheDocument()
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
