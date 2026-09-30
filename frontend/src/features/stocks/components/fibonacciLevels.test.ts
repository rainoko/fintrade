import { describe, expect, it } from 'vitest'
import {
  FIBONACCI_RATIOS,
  computeFibonacciLevels,
  findFibonacciSwing,
  formatFibonacciRatioLabel,
  selectVisibleBars,
  type FibonacciBar,
} from './fibonacciLevels'

// Hand-computed reference bars for an uptrend swing (the more recent extreme
// is the HIGH, 2026-08-04): highest high 120 (2026-08-04), lowest low 90
// (2026-08-03). Range = 30.
const uptrendBars: FibonacciBar[] = [
  { date: '2026-08-01', high: 100, low: 95 },
  { date: '2026-08-02', high: 110, low: 98 },
  { date: '2026-08-03', high: 105, low: 90 },
  { date: '2026-08-04', high: 120, low: 100 },
  { date: '2026-08-05', high: 115, low: 105 },
]

// The mirror-image downtrend swing: the more recent extreme is the LOW
// (2026-08-03). Same 120/90 highest-high/lowest-low pair, same range (30),
// opposite direction.
const downtrendBars: FibonacciBar[] = [
  { date: '2026-08-01', high: 120, low: 100 },
  { date: '2026-08-02', high: 110, low: 98 },
  { date: '2026-08-03', high: 105, low: 90 },
]

describe('findFibonacciSwing', () => {
  it('is null when fewer than 2 bars are given', () => {
    expect(findFibonacciSwing([])).toBeNull()
    expect(findFibonacciSwing([{ date: '2026-08-01', high: 100, low: 90 }])).toBeNull()
  })

  it('is null when every bar shares the exact same high/low (a flat range with no spread)', () => {
    const flatBars: FibonacciBar[] = [
      { date: '2026-08-01', high: 100, low: 100 },
      { date: '2026-08-02', high: 100, low: 100 },
    ]
    expect(findFibonacciSwing(flatBars)).toBeNull()
  })

  it('finds the highest-high/lowest-low pair and reads "up" when the high is the more recent extreme', () => {
    expect(findFibonacciSwing(uptrendBars)).toEqual({
      highPrice: 120,
      highDate: '2026-08-04',
      lowPrice: 90,
      lowDate: '2026-08-03',
      direction: 'up',
    })
  })

  it('reads "down" when the low is the more recent extreme', () => {
    expect(findFibonacciSwing(downtrendBars)).toEqual({
      highPrice: 120,
      highDate: '2026-08-01',
      lowPrice: 90,
      lowDate: '2026-08-03',
      direction: 'down',
    })
  })

  it('defaults to "up" when the high and low bar share the same date (a tie, e.g. a single bar is both extremes)', () => {
    const tiedBars: FibonacciBar[] = [
      { date: '2026-08-01', high: 100, low: 90 },
      { date: '2026-08-02', high: 95, low: 92 },
    ]
    expect(findFibonacciSwing(tiedBars)?.direction).toBe('up')
  })

  it('keeps the MOST RECENT bar (not the first) when the swing high recurs across distinct bars, and the tie-break flips `direction` relative to keeping the first one (frontend-fibonacci-auto-levels-followups)', () => {
    // day3's high (100) ties day1's high (100). A strict `>` comparison
    // would keep day1 as the swing-high bar (the bug this test guards
    // against); the fix keeps day3 (the most recent). The swing low is
    // day2. With day1 as the (buggy) high bar, lowBar.date (day2) <
    // highBar.date (day1) is false, giving 'down'; with day3 as the
    // (fixed) high bar, lowBar.date (day2) < highBar.date (day3) is true,
    // giving 'up' -- so this case demonstrates the tie-break actually
    // flipping the computed direction, not just the recorded date.
    const tiedHighBars: FibonacciBar[] = [
      { date: '2026-08-01', high: 100, low: 95 },
      { date: '2026-08-02', high: 90, low: 80 },
      { date: '2026-08-03', high: 100, low: 92 },
      { date: '2026-08-04', high: 85, low: 85 },
    ]
    expect(findFibonacciSwing(tiedHighBars)).toEqual({
      highPrice: 100,
      highDate: '2026-08-03',
      lowPrice: 80,
      lowDate: '2026-08-02',
      direction: 'up',
    })
  })

  it('keeps the MOST RECENT bar (not the first) when the swing low recurs across distinct bars (mirror image of the tied-high case)', () => {
    // day3's low (80) ties day1's low (80). A strict `<` comparison would
    // keep day1 as the swing-low bar; the fix keeps day3. The swing high is
    // day2. With day1 as the (buggy) low bar, lowBar.date (day1) <
    // highBar.date (day2) is true, giving 'up'; with day3 as the (fixed)
    // low bar, lowBar.date (day3) < highBar.date (day2) is false, giving
    // 'down' -- again a genuine direction flip, not just a date change.
    const tiedLowBars: FibonacciBar[] = [
      { date: '2026-08-01', high: 80, low: 80 },
      { date: '2026-08-02', high: 110, low: 90 },
      { date: '2026-08-03', high: 85, low: 80 },
      { date: '2026-08-04', high: 75, low: 95 },
    ]
    expect(findFibonacciSwing(tiedLowBars)).toEqual({
      highPrice: 110,
      highDate: '2026-08-02',
      lowPrice: 80,
      lowDate: '2026-08-03',
      direction: 'down',
    })
  })
})

describe('computeFibonacciLevels', () => {
  it('computes the 7 standard retracement levels for an uptrend swing (0% at the high, 100% at the low)', () => {
    const swing = findFibonacciSwing(uptrendBars)
    expect(swing).not.toBeNull()
    const levels = computeFibonacciLevels(swing!)
    // Hand-computed: price = 120 - ratio * 30
    expect(levels).toEqual([
      { ratio: 0, price: 120 },
      { ratio: 0.236, price: 112.92 },
      { ratio: 0.382, price: 108.54 },
      { ratio: 0.5, price: 105 },
      { ratio: 0.618, price: 101.46 },
      { ratio: 0.786, price: 96.42 },
      { ratio: 1, price: 90 },
    ])
  })

  it('computes the mirror-image levels for a downtrend swing (0% at the low, 100% at the high)', () => {
    const swing = findFibonacciSwing(downtrendBars)
    expect(swing).not.toBeNull()
    const levels = computeFibonacciLevels(swing!)
    // Hand-computed: price = 90 + ratio * 30
    expect(levels).toEqual([
      { ratio: 0, price: 90 },
      { ratio: 0.236, price: 97.08 },
      { ratio: 0.382, price: 101.46 },
      { ratio: 0.5, price: 105 },
      { ratio: 0.618, price: 108.54 },
      { ratio: 0.786, price: 113.58 },
      { ratio: 1, price: 120 },
    ])
  })

  it('always produces exactly one level per FIBONACCI_RATIOS entry, in order', () => {
    const swing = findFibonacciSwing(uptrendBars)
    const levels = computeFibonacciLevels(swing!)
    expect(levels.map((level) => level.ratio)).toEqual(FIBONACCI_RATIOS)
  })
})

describe('selectVisibleBars', () => {
  it('keeps only bars within the [firstDate, lastDate] inclusive window', () => {
    expect(selectVisibleBars(uptrendBars, '2026-08-02', '2026-08-04')).toEqual([
      { date: '2026-08-02', high: 110, low: 98 },
      { date: '2026-08-03', high: 105, low: 90 },
      { date: '2026-08-04', high: 120, low: 100 },
    ])
  })

  it('returns an empty array when no bar falls inside the window', () => {
    expect(selectVisibleBars(uptrendBars, '2025-01-01', '2025-01-02')).toEqual([])
  })
})

describe('formatFibonacciRatioLabel', () => {
  it('formats whole-number ratios (0/50/100%) with no trailing decimal', () => {
    expect(formatFibonacciRatioLabel(0)).toBe('0%')
    expect(formatFibonacciRatioLabel(0.5)).toBe('50%')
    expect(formatFibonacciRatioLabel(1)).toBe('100%')
  })

  it('formats fractional ratios to one decimal place', () => {
    expect(formatFibonacciRatioLabel(0.236)).toBe('23.6%')
    expect(formatFibonacciRatioLabel(0.382)).toBe('38.2%')
    expect(formatFibonacciRatioLabel(0.618)).toBe('61.8%')
    expect(formatFibonacciRatioLabel(0.786)).toBe('78.6%')
  })
})
