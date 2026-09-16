import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { renderWithTheme } from '../../../../tests/renderWithTheme'
import ConfidenceGauge from './ConfidenceGauge'
import { confidenceBand } from './confidenceBand'

// Boundary values per docs/Analyse.md §6: <40% = Low, 40-70% = Medium, >70% = High.
describe('confidenceBand', () => {
  it('returns Low below 40', () => {
    expect(confidenceBand(0)).toBe('Low')
    expect(confidenceBand(39)).toBe('Low')
  })

  it('returns Medium at the 40 lower edge and up to 70', () => {
    expect(confidenceBand(40)).toBe('Medium')
    expect(confidenceBand(70)).toBe('Medium')
  })

  it('returns High above 70', () => {
    expect(confidenceBand(71)).toBe('High')
    expect(confidenceBand(100)).toBe('High')
  })
})

describe('ConfidenceGauge', () => {
  it('renders the raw percentage and Low band at 0', () => {
    renderWithTheme(<ConfidenceGauge confidence={0} />)

    expect(screen.getByText(/0%/)).toBeInTheDocument()
    expect(screen.getByText(/Low/)).toBeInTheDocument()
  })

  it('renders the raw percentage and Low band at 39', () => {
    renderWithTheme(<ConfidenceGauge confidence={39} />)

    expect(screen.getByText(/39%/)).toBeInTheDocument()
    expect(screen.getByText(/Low/)).toBeInTheDocument()
  })

  it('renders the Medium band at the 40 edge', () => {
    renderWithTheme(<ConfidenceGauge confidence={40} />)

    expect(screen.getByText(/40%/)).toBeInTheDocument()
    expect(screen.getByText(/Medium/)).toBeInTheDocument()
  })

  it('renders the Medium band at the 70 edge', () => {
    renderWithTheme(<ConfidenceGauge confidence={70} />)

    expect(screen.getByText(/70%/)).toBeInTheDocument()
    expect(screen.getByText(/Medium/)).toBeInTheDocument()
  })

  it('renders the High band at 71', () => {
    renderWithTheme(<ConfidenceGauge confidence={71} />)

    expect(screen.getByText(/71%/)).toBeInTheDocument()
    expect(screen.getByText(/High/)).toBeInTheDocument()
  })

  it('renders the raw percentage and High band at 100', () => {
    renderWithTheme(<ConfidenceGauge confidence={100} />)

    expect(screen.getByText(/100%/)).toBeInTheDocument()
    expect(screen.getByText(/High/)).toBeInTheDocument()
  })

  it('exposes an accessible progressbar with the raw value', () => {
    renderWithTheme(<ConfidenceGauge confidence={65} />)

    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '65')
  })
})
