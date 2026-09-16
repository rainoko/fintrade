import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import PageHeader from './PageHeader'

describe('PageHeader', () => {
  it('renders the title as a level-1 heading', () => {
    render(<PageHeader title="Portfolio" />)

    expect(
      screen.getByRole('heading', { level: 1, name: 'Portfolio' }),
    ).toBeInTheDocument()
  })

  it('renders no action slot when none is given', () => {
    render(<PageHeader title="Portfolio" />)

    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('renders the action slot when given', () => {
    render(
      <PageHeader
        title="Portfolio"
        action={<button type="button">Add Position</button>}
      />,
    )

    expect(screen.getByRole('button', { name: 'Add Position' })).toBeInTheDocument()
  })
})
