import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { renderWithTheme } from '../../../../tests/renderWithTheme'
import { theme } from '../../../theme/theme'
import SignalBadge from './SignalBadge'

describe('SignalBadge', () => {
  it('renders the BUY label in the buy color', () => {
    renderWithTheme(<SignalBadge signal="BUY" />)

    expect(screen.getByText('BUY')).toBeInTheDocument()
    expect(screen.getByTestId('signal-badge')).toHaveStyle({
      backgroundColor: theme.palette.signal.buy,
    })
  })

  it('renders the SELL label in the sell color', () => {
    renderWithTheme(<SignalBadge signal="SELL" />)

    expect(screen.getByText('SELL')).toBeInTheDocument()
    expect(screen.getByTestId('signal-badge')).toHaveStyle({
      backgroundColor: theme.palette.signal.sell,
    })
  })

  it('renders the HOLD label in the hold color', () => {
    renderWithTheme(<SignalBadge signal="HOLD" />)

    expect(screen.getByText('HOLD')).toBeInTheDocument()
    expect(screen.getByTestId('signal-badge')).toHaveStyle({
      backgroundColor: theme.palette.signal.hold,
    })
  })
})
