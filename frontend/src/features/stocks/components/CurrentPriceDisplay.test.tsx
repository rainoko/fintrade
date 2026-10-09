import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { renderWithTheme } from '../../../../tests/renderWithTheme'
import CurrentPriceDisplay from './CurrentPriceDisplay'

describe('CurrentPriceDisplay', () => {
  it('renders the formatted current price with a positive day-over-day change', () => {
    renderWithTheme(<CurrentPriceDisplay currentPrice={228.9} changePct={1.4} />)

    expect(screen.getByTestId('current-price')).toHaveTextContent('$228.90')
    expect(screen.getByText('+1.40%')).toBeInTheDocument()
  })

  it('renders a negative day-over-day change', () => {
    renderWithTheme(<CurrentPriceDisplay currentPrice={95.25} changePct={-2.3} />)

    expect(screen.getByTestId('current-price')).toHaveTextContent('$95.25')
    expect(screen.getByText('-2.30%')).toBeInTheDocument()
  })

  it('omits the delta entirely when changePct is null (no prior bar to diff against)', () => {
    renderWithTheme(<CurrentPriceDisplay currentPrice={50.0} changePct={null} />)

    expect(screen.getByTestId('current-price')).toHaveTextContent('$50.00')
    expect(screen.queryByText(/%/)).not.toBeInTheDocument()
  })
})
