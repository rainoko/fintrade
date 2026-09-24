import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { renderWithTheme } from '../../../../tests/renderWithTheme'
import IbkrStatusBadge from './IbkrStatusBadge'

describe('IbkrStatusBadge', () => {
  it('renders the disabled state as a default-colored chip with its fixed explanation', () => {
    renderWithTheme(<IbkrStatusBadge state="disabled" />)

    const chip = screen.getByTestId('ibkr-status-badge')
    expect(screen.getByText('IBKR: Disabled')).toBeInTheDocument()
    expect(chip.className).toContain('MuiChip-colorDefault')
    expect(chip).toHaveAttribute(
      'aria-label',
      expect.stringContaining('The optional IBKR Client Portal Gateway integration is turned off.'),
    )
  })

  it('renders the available state as a success-colored chip', () => {
    renderWithTheme(<IbkrStatusBadge state="available" />)

    const chip = screen.getByTestId('ibkr-status-badge')
    expect(screen.getByText('IBKR: Connected')).toBeInTheDocument()
    expect(chip.className).toContain('MuiChip-colorSuccess')
  })

  it('renders the gateway_unreachable state as an error-colored chip', () => {
    renderWithTheme(<IbkrStatusBadge state="gateway_unreachable" />)

    const chip = screen.getByTestId('ibkr-status-badge')
    expect(screen.getByText('IBKR: Gateway down')).toBeInTheDocument()
    expect(chip.className).toContain('MuiChip-colorError')
  })

  it('renders the not_authenticated state as a warning-colored chip', () => {
    renderWithTheme(<IbkrStatusBadge state="not_authenticated" />)

    const chip = screen.getByTestId('ibkr-status-badge')
    expect(screen.getByText('IBKR: Sign-in needed')).toBeInTheDocument()
    expect(chip.className).toContain('MuiChip-colorWarning')
  })

  it("prefers the response's own detail text over the fixed fallback explanation, when present", () => {
    renderWithTheme(
      <IbkrStatusBadge
        state="gateway_unreachable"
        detail="IBKR gateway request to /iserver/auth/status failed"
      />,
    )

    expect(screen.getByTestId('ibkr-status-badge')).toHaveAttribute(
      'aria-label',
      expect.stringContaining('IBKR gateway request to /iserver/auth/status failed'),
    )
  })

  it('falls back to the fixed explanation when detail is null', () => {
    renderWithTheme(<IbkrStatusBadge state="available" detail={null} />)

    expect(screen.getByTestId('ibkr-status-badge')).toHaveAttribute(
      'aria-label',
      expect.stringContaining('authenticated'),
    )
  })
})
