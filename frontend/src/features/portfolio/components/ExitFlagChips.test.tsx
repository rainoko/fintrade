import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import ExitFlagChips from './ExitFlagChips'

describe('ExitFlagChips', () => {
  it('renders an em dash when there are no flags', () => {
    render(<ExitFlagChips flags={[]} />)

    expect(screen.getByText('—')).toBeInTheDocument()
  })

  it('renders a Chip per flag with its human-readable label', () => {
    render(<ExitFlagChips flags={['two_percent_rule_breached', 'stop_hit']} />)

    expect(screen.getByText('2% rule breached')).toBeInTheDocument()
    expect(screen.getByText('Stop hit')).toBeInTheDocument()
    expect(screen.queryByText('two_percent_rule_breached')).not.toBeInTheDocument()
  })

  it('falls back to a humanized label for a flag not in the known label map', () => {
    render(<ExitFlagChips flags={['some_future_flag']} />)

    expect(screen.getByText('Some future flag')).toBeInTheDocument()
  })
})
