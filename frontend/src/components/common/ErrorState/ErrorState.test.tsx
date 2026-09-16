import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ApiError } from '../../../api/client'
import ErrorState from './ErrorState'

describe('ErrorState', () => {
  it('renders a distinct message for a 404 unknown-resource error', () => {
    render(<ErrorState error={new ApiError(404, "Ticker 'ZZZZ' not found")} />)

    expect(screen.getByText('Not found')).toBeInTheDocument()
    expect(screen.getByText("Ticker 'ZZZZ' not found")).toBeInTheDocument()
  })

  it('renders a distinct message for a 422 validation/insufficient-history error', () => {
    render(
      <ErrorState
        error={new ApiError(422, 'Insufficient history to compute weekly indicators')}
      />,
    )

    expect(screen.getByText('Unable to process request')).toBeInTheDocument()
    expect(
      screen.getByText('Insufficient history to compute weekly indicators'),
    ).toBeInTheDocument()
  })

  it('renders a distinct message for a 503 provider-unavailable error', () => {
    render(<ErrorState error={new ApiError(503, 'Market data provider unavailable')} />)

    expect(screen.getByText('Service unavailable')).toBeInTheDocument()
    expect(screen.getByText('Market data provider unavailable')).toBeInTheDocument()
  })

  it('renders a distinct message for a network failure (status 0)', () => {
    render(
      <ErrorState
        error={
          new ApiError(0, 'Unable to reach the API. Check your connection and try again.')
        }
      />,
    )

    expect(screen.getByText('Connection error')).toBeInTheDocument()
  })

  it('falls back to a generic heading for an unrecognized status', () => {
    render(<ErrorState error={new ApiError(500, 'Internal server error')} />)

    expect(screen.getByText('Something went wrong')).toBeInTheDocument()
  })

  it('uses the alert role so assistive tech announces it', () => {
    render(<ErrorState error={new ApiError(404, 'Not found')} />)

    expect(screen.getByRole('alert')).toBeInTheDocument()
  })
})
