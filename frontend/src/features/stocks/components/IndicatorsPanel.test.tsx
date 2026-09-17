import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { Indicators } from '../../../api/stocks'
import { renderWithTheme } from '../../../../tests/renderWithTheme'
import IndicatorsPanel from './IndicatorsPanel'

const indicators: Indicators = {
  ema_13: 226.4,
  ema_26: 221.7,
  macd_histogram: 1.82,
  bull_power: 3.1,
  bear_power: -1.4,
}

describe('IndicatorsPanel', () => {
  it('renders the latest ema/macd/elder-ray values as a stat grid, not a chart', () => {
    renderWithTheme(<IndicatorsPanel indicators={indicators} />)

    expect(screen.getByText('EMA (13)')).toBeInTheDocument()
    expect(screen.getByText('226.40')).toBeInTheDocument()
    expect(screen.getByText('EMA (26)')).toBeInTheDocument()
    expect(screen.getByText('221.70')).toBeInTheDocument()
    expect(screen.getByText('MACD Histogram')).toBeInTheDocument()
    expect(screen.getByText('1.82')).toBeInTheDocument()
    expect(screen.getByText('Bull Power')).toBeInTheDocument()
    expect(screen.getByText('3.10')).toBeInTheDocument()
    expect(screen.getByText('Bear Power')).toBeInTheDocument()
    expect(screen.getByText('-1.40')).toBeInTheDocument()

    expect(screen.queryByRole('img')).not.toBeInTheDocument()
  })
})
