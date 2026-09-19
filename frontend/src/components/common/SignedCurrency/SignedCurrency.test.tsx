import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { theme } from '../../../theme/theme'
import SignedCurrency from './SignedCurrency'

describe('SignedCurrency', () => {
  it('renders a positive value with a leading + and success color', () => {
    render(<SignedCurrency value={201} />)

    const el = screen.getByText('+$201.00')
    expect(el).toHaveStyle({ color: theme.palette.success.main })
  })

  it('renders a negative value with no extra sign and error color', () => {
    render(<SignedCurrency value={-84.5} />)

    const el = screen.getByText('-$84.50')
    expect(el).toHaveStyle({ color: theme.palette.error.main })
  })

  it('renders zero with no sign and a neutral color', () => {
    render(<SignedCurrency value={0} />)

    const el = screen.getByText('$0.00')
    expect(el).toHaveStyle({ color: theme.palette.text.secondary })
  })

  it('applies thousands separators via formatCurrency', () => {
    render(<SignedCurrency value={1234.5} />)

    expect(screen.getByText('+$1,234.50')).toBeInTheDocument()
  })
})
