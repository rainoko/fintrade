import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import TickerLink from './TickerLink'

function renderWithRouter(ticker: string) {
  return render(
    <MemoryRouter>
      <TickerLink ticker={ticker} />
    </MemoryRouter>,
  )
}

describe('TickerLink', () => {
  it('renders the ticker as link text pointing at its stock detail page', () => {
    renderWithRouter('AAPL')

    const link = screen.getByRole('link', { name: 'AAPL' })
    expect(link).toHaveAttribute('href', '/stocks/AAPL')
  })

  it('URI-encodes a ticker containing characters not safe in a raw path segment', () => {
    renderWithRouter('BRK.B')

    const link = screen.getByRole('link', { name: 'BRK.B' })
    expect(link).toHaveAttribute('href', '/stocks/BRK.B')
  })

  it('encodes a ticker containing a slash so it does not create an extra path segment', () => {
    renderWithRouter('AB/C')

    const link = screen.getByRole('link', { name: 'AB/C' })
    expect(link).toHaveAttribute('href', '/stocks/AB%2FC')
  })
})
