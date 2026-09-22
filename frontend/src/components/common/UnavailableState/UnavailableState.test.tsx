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
      screen.getByText('IBKR integration is disabled (FINTRADE_IBKR_ENABLED is not set).'),
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

  it('does not use the alert role, unlike ErrorState — nothing has gone wrong', () => {
    render(<UnavailableState heading="Scanner unavailable" />)

    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})
