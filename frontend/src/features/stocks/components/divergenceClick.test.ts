import type { MouseEventParams, Time } from 'lightweight-charts'
import { describe, expect, it } from 'vitest'
import type { DivergenceOut } from '../../../api/stocks'
import { clickedDivergenceExtreme, isDivergenceInRange } from './divergenceClick'

const divergence: DivergenceOut = {
  indicator: 'macd_histogram',
  kind: 'bullish',
  first_extreme_date: '2026-08-03',
  first_extreme_price: 210.5,
  first_extreme_indicator_value: -6.0,
  second_extreme_date: '2026-08-31',
  second_extreme_price: 205.2,
  second_extreme_indicator_value: -1.5,
  bars_apart: 20,
  centerline_crossed: true,
  beyond_reference_line: null,
  aborted: false,
}

function param(time: Time | undefined): MouseEventParams<Time> {
  return { time, seriesData: new Map() } as MouseEventParams<Time>
}

describe('clickedDivergenceExtreme', () => {
  it('is true when the click time matches the first extreme date', () => {
    expect(clickedDivergenceExtreme(divergence, param('2026-08-03'))).toBe(true)
  })

  it('is true when the click time matches the second extreme date', () => {
    expect(clickedDivergenceExtreme(divergence, param('2026-08-31'))).toBe(true)
  })

  it('is false for an unrelated date', () => {
    expect(clickedDivergenceExtreme(divergence, param('2026-09-02'))).toBe(false)
  })

  it('is false when the click has no time at all (outside the plotted data range)', () => {
    expect(clickedDivergenceExtreme(divergence, param(undefined))).toBe(false)
  })

  it('matches a BusinessDay-shaped click time against the same date', () => {
    expect(
      clickedDivergenceExtreme(divergence, param({ year: 2026, month: 8, day: 3 })),
    ).toBe(true)
  })
})

describe('isDivergenceInRange', () => {
  it('is true when both extreme dates fall within the visible range', () => {
    expect(isDivergenceInRange(divergence, '2026-08-01', '2026-09-02')).toBe(true)
  })

  it('is true when both extreme dates exactly equal the range bounds', () => {
    expect(isDivergenceInRange(divergence, '2026-08-03', '2026-08-31')).toBe(true)
  })

  it('is false when the first extreme date falls before the visible range', () => {
    // Range starts after the first extreme (2026-08-03) -- e.g. a 1M
    // preset while the divergence itself is months old.
    expect(isDivergenceInRange(divergence, '2026-08-15', '2026-09-02')).toBe(false)
  })

  it('is false when the second extreme date falls after the visible range', () => {
    expect(isDivergenceInRange(divergence, '2026-08-01', '2026-08-15')).toBe(false)
  })

  it('is false when neither extreme date falls within the visible range', () => {
    expect(isDivergenceInRange(divergence, '2026-09-01', '2026-09-02')).toBe(false)
  })
})
