import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import StatCard from './StatCard'

describe('StatCard', () => {
  it('renders the label and value', () => {
    render(<StatCard label="Total Equity" value="$10,000.00" />)

    expect(screen.getByText('Total Equity')).toBeInTheDocument()
    expect(screen.getByText('$10,000.00')).toBeInTheDocument()
  })

  it('renders no delta when none is given', () => {
    render(<StatCard label="Total Equity" value="$10,000.00" />)

    expect(screen.queryByText(/%/)).not.toBeInTheDocument()
  })

  it('renders a positive delta', () => {
    render(
      <StatCard
        label="Total Equity"
        value="$10,000.00"
        delta={{ text: '+3.20%', direction: 'positive' }}
      />,
    )

    expect(screen.getByText('+3.20%')).toBeInTheDocument()
  })

  it('renders a negative delta', () => {
    render(
      <StatCard
        label="Open Risk"
        value="6.50%"
        delta={{ text: '-0.80%', direction: 'negative' }}
      />,
    )

    expect(screen.getByText('-0.80%')).toBeInTheDocument()
  })

  it('renders a neutral delta', () => {
    render(
      <StatCard
        label="Positions"
        value="4"
        delta={{ text: 'no change', direction: 'neutral' }}
      />,
    )

    expect(screen.getByText('no change')).toBeInTheDocument()
  })
})
