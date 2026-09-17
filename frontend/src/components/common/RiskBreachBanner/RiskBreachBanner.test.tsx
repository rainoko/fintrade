import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { renderWithTheme } from '../../../../tests/renderWithTheme'
import { theme } from '../../../theme/theme'
import RiskBreachBanner from './RiskBreachBanner'

describe('RiskBreachBanner', () => {
  it('renders the given message with an alert role', () => {
    renderWithTheme(<RiskBreachBanner message="6% rule breached — trim your positions." />)

    const alert = screen.getByRole('alert')
    expect(alert).toHaveTextContent('6% rule breached — trim your positions.')
  })

  it('styles the message in the riskBreach warning color', () => {
    renderWithTheme(<RiskBreachBanner message="Breach!" />)

    expect(screen.getByText('Breach!')).toHaveStyle({ color: theme.palette.riskBreach.main })
  })
})
