import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { renderWithTheme } from '../../../../tests/renderWithTheme'
import { theme } from '../../../theme/theme'
import RiskPercent from './RiskPercent'

describe('RiskPercent', () => {
  it('renders a within-limit value in a neutral color, with no leading sign', () => {
    renderWithTheme(<RiskPercent value={1.8} />)

    const el = screen.getByText('1.80%')
    expect(el).toHaveStyle({ color: theme.palette.text.secondary })
  })

  it('renders a breached value in the riskBreach warning color', () => {
    renderWithTheme(<RiskPercent value={5} breached />)

    const el = screen.getByText('5.00%')
    expect(el).toHaveStyle({ color: theme.palette.riskBreach.main })
  })

  it('respects a custom decimals count', () => {
    renderWithTheme(<RiskPercent value={1.23456} decimals={1} />)

    expect(screen.getByText('1.2%')).toBeInTheDocument()
  })
})
