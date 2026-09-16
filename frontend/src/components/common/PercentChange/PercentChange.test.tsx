import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { theme } from '../../../theme/theme'
import PercentChange from './PercentChange'

describe('PercentChange', () => {
  it('renders a positive value with a leading + and success color', () => {
    render(<PercentChange value={3.2} />)

    const el = screen.getByText('+3.20%')
    expect(el).toHaveStyle({ color: theme.palette.success.main })
  })

  it('renders a negative value with no extra sign and error color', () => {
    render(<PercentChange value={-1.5} />)

    const el = screen.getByText('-1.50%')
    expect(el).toHaveStyle({ color: theme.palette.error.main })
  })

  it('renders zero with no sign and a neutral color', () => {
    render(<PercentChange value={0} />)

    const el = screen.getByText('0.00%')
    expect(el).toHaveStyle({ color: theme.palette.text.secondary })
  })

  it('respects a custom decimals count', () => {
    render(<PercentChange value={3.14159} decimals={1} />)

    expect(screen.getByText('+3.1%')).toBeInTheDocument()
  })
})
