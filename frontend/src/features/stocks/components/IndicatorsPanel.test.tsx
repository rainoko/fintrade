import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
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
  trend_strength: { atr: 4.2, plus_di: 28.5, minus_di: 15.3, adx: 22.1 },
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

  it('renders a fallback instead of crashing when the API returns null indicator values', () => {
    // `Indicators`' fields are declared as non-optional `number`, but the backend can
    // legitimately serialize them as JSON `null` when the latest daily bar hasn't
    // settled yet (NaN indicators -> pydantic's ser_json_inf_nan='null'). Simulate that
    // real-world payload shape here regardless of what the generated type claims, per
    // this task's fix.
    const indicatorsWithNulls: Indicators = {
      ema_13: 226.4,
      ema_26: 221.7,
      macd_histogram: 1.82,
      bull_power: null as unknown as number,
      bear_power: null as unknown as number,
      trend_strength: { atr: 4.2, plus_di: 28.5, minus_di: 15.3, adx: 22.1 },
    }

    expect(() =>
      renderWithTheme(<IndicatorsPanel indicators={indicatorsWithNulls} />),
    ).not.toThrow()

    expect(screen.getByText('226.40')).toBeInTheDocument()
    const dashes = screen.getAllByText('—')
    expect(dashes).toHaveLength(2)
  })

  it('wires the right MetricHelp content to the right StatCard corner icon', async () => {
    const user = userEvent.setup()
    renderWithTheme(<IndicatorsPanel indicators={indicators} />)

    // EMA (13)'s help icon should open EMA13-specific current-value text,
    // not e.g. Bull Power's or MACD Histogram's.
    await user.click(screen.getByRole('button', { name: 'EMA (13) help' }))
    expect(screen.getByText(/Currently 226\.40, above EMA\(26\)/)).toBeInTheDocument()
    await user.keyboard('{Escape}')
    expect(screen.queryByText(/above EMA\(26\)/)).not.toBeInTheDocument()

    // Bull Power's icon should open Bull-Power-specific content instead.
    await user.click(screen.getByRole('button', { name: 'Bull Power help' }))
    expect(
      screen.getByText(
        /Currently 3\.10 -- positive: today’s high traded above EMA\(13\)/,
      ),
    ).toBeInTheDocument()
    expect(screen.queryByText(/above EMA\(26\)/)).not.toBeInTheDocument()
  })
})
