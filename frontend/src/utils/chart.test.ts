import { describe, expect, it } from 'vitest'
import type { BusinessDay, UTCTimestamp } from 'lightweight-charts'
import { timeToDateString } from './chart'

// `bringSeriesToFront`/`isFiniteNumber`/`createBaseChart` are already
// exercised indirectly (and thoroughly, across many cases) by
// `PriceChart.test.tsx`/`OscillatorChart.test.tsx`'s own mocked-chart
// tests -- this file covers `timeToDateString` (frontend-divergence-markers)
// directly instead, since none of those component tests happen to feed it
// anything but a plain date string (the only shape this app has ever fed
// the library `time` as), leaving its `BusinessDay`/`UTCTimestamp` branches
// otherwise untested.
describe('timeToDateString', () => {
  it('returns a plain date string unchanged', () => {
    expect(timeToDateString('2026-08-31')).toBe('2026-08-31')
  })

  it('formats a BusinessDay object as YYYY-MM-DD, zero-padding month/day', () => {
    const businessDay: BusinessDay = { year: 2026, month: 3, day: 5 }
    expect(timeToDateString(businessDay)).toBe('2026-03-05')
  })

  it('does not zero-pad a month/day that is already two digits', () => {
    const businessDay: BusinessDay = { year: 2026, month: 12, day: 25 }
    expect(timeToDateString(businessDay)).toBe('2026-12-25')
  })

  it('formats a UTCTimestamp (seconds since epoch) as its UTC date', () => {
    // 2026-01-15T00:00:00Z
    const timestamp = 1768435200 as UTCTimestamp
    expect(timeToDateString(timestamp)).toBe('2026-01-15')
  })
})
