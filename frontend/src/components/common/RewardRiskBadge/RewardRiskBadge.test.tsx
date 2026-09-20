import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { renderWithTheme } from '../../../../tests/renderWithTheme'
import { theme } from '../../../theme/theme'
import RewardRiskBadge from './RewardRiskBadge'

describe('RewardRiskBadge', () => {
  it('renders a passing ratio in success color with no warning icon', () => {
    renderWithTheme(<RewardRiskBadge ratio={2.4} meetsMinimum />)

    const el = screen.getByText('2.4:1')
    expect(el).toHaveStyle({ color: theme.palette.success.main })
    expect(screen.queryByLabelText('Below the 2:1 minimum')).not.toBeInTheDocument()
  })

  it('renders a failing ratio in the riskBreach warning color with a warning icon', () => {
    renderWithTheme(<RewardRiskBadge ratio={1.3} meetsMinimum={false} />)

    const el = screen.getByText('1.3:1')
    expect(el).toHaveStyle({ color: theme.palette.riskBreach.main, fontWeight: 700 })
    expect(screen.getByLabelText('Below the 2:1 minimum')).toBeInTheDocument()
  })

  it('renders "n/a" in a neutral color, never flagged, when the ratio is null', () => {
    renderWithTheme(<RewardRiskBadge ratio={null} meetsMinimum={false} />)

    const el = screen.getByText('n/a')
    expect(el).toHaveStyle({ color: theme.palette.text.secondary })
    expect(screen.queryByLabelText('Below the 2:1 minimum')).not.toBeInTheDocument()
  })

  it('respects a custom decimals count', () => {
    renderWithTheme(<RewardRiskBadge ratio={2.34567} meetsMinimum decimals={2} />)

    expect(screen.getByText('2.35:1')).toBeInTheDocument()
  })
})
