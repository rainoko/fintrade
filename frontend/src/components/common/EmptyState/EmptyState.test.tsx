import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import EmptyState from './EmptyState'

describe('EmptyState', () => {
  it('renders the given message', () => {
    render(<EmptyState message="No positions yet" />)

    expect(screen.getByText('No positions yet')).toBeInTheDocument()
  })

  it('renders no action by default', () => {
    render(<EmptyState message="No positions yet" />)

    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('renders an action when given', () => {
    render(
      <EmptyState
        message="No positions yet"
        action={<button type="button">Add Position</button>}
      />,
    )

    expect(screen.getByRole('button', { name: 'Add Position' })).toBeInTheDocument()
  })
})
