import Typography from '@mui/material/Typography'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { renderWithTheme } from '../../../../tests/renderWithTheme'
import LegendToggle from './LegendToggle'

describe('LegendToggle', () => {
  it('renders the swatch/label content with aria-pressed=true and full opacity when active', () => {
    renderWithTheme(
      <LegendToggle active label="Channel" onToggle={vi.fn()}>
        <Typography>Channel (Autoenvelope)</Typography>
      </LegendToggle>,
    )

    const toggle = screen.getByRole('button', { name: 'Hide Channel on the chart' })
    expect(toggle).toHaveAttribute('aria-pressed', 'true')
    expect(toggle).toHaveStyle({ opacity: '1' })
    expect(screen.getByText('Channel (Autoenvelope)')).toBeInTheDocument()
  })

  it('dims the content and reports aria-pressed=false when inactive', () => {
    renderWithTheme(
      <LegendToggle active={false} label="Channel" onToggle={vi.fn()}>
        <Typography>Channel (Autoenvelope)</Typography>
      </LegendToggle>,
    )

    const toggle = screen.getByRole('button', { name: 'Show Channel on the chart' })
    expect(toggle).toHaveAttribute('aria-pressed', 'false')
    expect(toggle).toHaveStyle({ opacity: '0.45' })
  })

  it('calls onToggle on click', async () => {
    const user = userEvent.setup()
    const onToggle = vi.fn()
    renderWithTheme(
      <LegendToggle active label="Channel" onToggle={onToggle}>
        <Typography>Channel</Typography>
      </LegendToggle>,
    )

    await user.click(screen.getByRole('button', { name: 'Hide Channel on the chart' }))

    expect(onToggle).toHaveBeenCalledTimes(1)
  })

  it('calls onToggle on Enter/Space keyboard activation (native button semantics)', async () => {
    const user = userEvent.setup()
    const onToggle = vi.fn()
    renderWithTheme(
      <LegendToggle active label="Channel" onToggle={onToggle}>
        <Typography>Channel</Typography>
      </LegendToggle>,
    )

    const toggle = screen.getByRole('button', { name: 'Hide Channel on the chart' })
    toggle.focus()
    await user.keyboard('{Enter}')
    await user.keyboard(' ')

    expect(onToggle).toHaveBeenCalledTimes(2)
  })
})
