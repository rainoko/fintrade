import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import LoadingState from './LoadingState'

describe('LoadingState', () => {
  it('renders an accessible progress indicator', () => {
    render(<LoadingState />)

    expect(screen.getByRole('progressbar')).toBeInTheDocument()
  })

  it('renders no message by default', () => {
    render(<LoadingState />)

    expect(screen.queryByText(/loading/i)).not.toBeInTheDocument()
  })

  it('renders a message when given', () => {
    render(<LoadingState message="Loading portfolio..." />)

    expect(screen.getByText('Loading portfolio...')).toBeInTheDocument()
  })
})
