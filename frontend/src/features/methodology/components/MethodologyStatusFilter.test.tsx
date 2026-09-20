import { ThemeProvider } from '@mui/material/styles'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { theme } from '../../../theme/theme'
import type { MethodologyStatus } from '../data/methodologyContent'
import MethodologyStatusFilter from './MethodologyStatusFilter'

function renderFilter(selected: Set<MethodologyStatus>, onToggle = vi.fn()) {
  render(
    <ThemeProvider theme={theme}>
      <MethodologyStatusFilter selected={selected} onToggle={onToggle} />
    </ThemeProvider>,
  )
  return onToggle
}

describe('MethodologyStatusFilter', () => {
  it('renders one chip per status with its legend description', () => {
    renderFilter(new Set(['core_signal', 'risk_management', 'informational', 'considered']))

    expect(screen.getByText('Active — feeds the signal')).toBeInTheDocument()
    expect(screen.getByText('Active — feeds portfolio risk & money management')).toBeInTheDocument()
    expect(screen.getByText('Computed & exposed — informational only')).toBeInTheDocument()
    expect(screen.getByText('Considered — not yet implemented')).toBeInTheDocument()
  })

  it('marks a selected status chip as pressed and a deselected one as not pressed', () => {
    renderFilter(new Set(['core_signal']))

    const chips = screen.getAllByRole('button')
    const selectedChip = chips.find((chip) => chip.textContent === 'Active — feeds the signal')
    const deselectedChip = chips.find(
      (chip) => chip.textContent === 'Considered — not yet implemented',
    )

    expect(selectedChip).toHaveAttribute('aria-pressed', 'true')
    expect(deselectedChip).toHaveAttribute('aria-pressed', 'false')
  })

  it('calls onToggle with the clicked status', async () => {
    const user = userEvent.setup()
    const onToggle = renderFilter(new Set(['core_signal']))

    await user.click(screen.getByText('Considered — not yet implemented'))

    expect(onToggle).toHaveBeenCalledWith('considered')
  })
})
