import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import UnavailableState from './UnavailableState'

describe('UnavailableState', () => {
  it('renders the heading and message', () => {
    render(
      <UnavailableState
        heading="Scanner unavailable"
        message="IBKR integration is disabled (FINTRADE_IBKR_ENABLED is not set)."
      />,
    )

    expect(screen.getByText('Scanner unavailable')).toBeInTheDocument()
    expect(
      screen.getByText(
        'IBKR integration is disabled (FINTRADE_IBKR_ENABLED is not set).',
      ),
    ).toBeInTheDocument()
  })

  it('renders just the heading when no message is given', () => {
    render(<UnavailableState heading="Scanner unavailable" />)

    expect(screen.getByText('Scanner unavailable')).toBeInTheDocument()
  })

  it('renders just the heading when message is explicitly null', () => {
    render(<UnavailableState heading="Scanner unavailable" message={null} />)

    expect(screen.getByText('Scanner unavailable')).toBeInTheDocument()
  })

  it('renders just the heading when message is a blank string, distinct from null (backend detail: "")', () => {
    // '' is a valid, distinct value from null for a `string | null` field -- a plain
    // `{message && (...)}` check would silently swallow it into a bare heading, which is
    // actually the desired outcome here, but a whitespace-only string ('   ', asserted in
    // the next test) would slip through that same bare truthy check and render a blank-
    // looking line. Both are asserted here by checking only one <p> element (the heading
    // itself, per PageHeader/UnavailableState's own `variant="h6" component="p"`) renders
    // at all, since an empty message's own Typography would otherwise still mount as a
    // second, empty <p>.
    const { container } = render(
      <UnavailableState heading="Scanner unavailable" message="" />,
    )

    expect(screen.getByText('Scanner unavailable')).toBeInTheDocument()
    expect(container.querySelectorAll('p')).toHaveLength(1)
  })

  it('renders just the heading when message is whitespace-only', () => {
    const { container } = render(
      <UnavailableState heading="Scanner unavailable" message="   " />,
    )

    expect(screen.getByText('Scanner unavailable')).toBeInTheDocument()
    expect(container.querySelectorAll('p')).toHaveLength(1)
  })

  it('does not use the alert role, unlike ErrorState — nothing has gone wrong', () => {
    render(<UnavailableState heading="Scanner unavailable" />)

    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})
