import { describe, expect, it } from 'vitest'
import {
  formatCurrency,
  formatDate,
  formatNullableCurrency,
  formatNullableNumber,
  formatSignedSpread,
  humanizeSnakeCase,
} from './format'

describe('humanizeSnakeCase', () => {
  it('returns the label map entry when the value is known', () => {
    expect(humanizeSnakeCase('stop_hit', { stop_hit: 'Stop hit' })).toBe('Stop hit')
  })

  it('falls back to underscores-to-spaces, capitalized, when no label map is given', () => {
    expect(humanizeSnakeCase('close_above_prior_high')).toBe('Close above prior high')
  })

  it('falls back the same way for a value not present in a given label map', () => {
    expect(humanizeSnakeCase('some_new_flag', { stop_hit: 'Stop hit' })).toBe(
      'Some new flag',
    )
  })

  it('lowercases an UPPER_SNAKE_CASE value before capitalizing only the first letter', () => {
    // Elder Triple Screen enum-like fields (tide.trend, wave.state, ...) come
    // back as UPPER_SNAKE_CASE, unlike confidence_breakdown component names
    // or exit_flags values (already lowercase) — the fallback has to
    // normalize both conventions to the same "Capitalized words" style.
    expect(humanizeSnakeCase('OVERSOLD_PULLBACK')).toBe('Oversold pullback')
  })
})

describe('formatNullableNumber', () => {
  it('formats a plain number using the given options', () => {
    expect(
      formatNullableNumber(24.3, { minimumFractionDigits: 1, maximumFractionDigits: 1 }),
    ).toBe('24.3')
  })

  it("renders '—' for null", () => {
    expect(formatNullableNumber(null)).toBe('—')
  })

  it("renders '—' for undefined", () => {
    expect(formatNullableNumber(undefined)).toBe('—')
  })

  it("renders '—' for NaN", () => {
    expect(formatNullableNumber(Number.NaN)).toBe('—')
  })

  it('formats negative numbers with grouping when no fraction-digit options are given', () => {
    expect(formatNullableNumber(-18234.5)).toBe('-18,234.5')
  })
})

describe('formatCurrency', () => {
  it('formats a sub-1000 value as USD with two decimal places', () => {
    expect(formatCurrency(150)).toBe('$150.00')
  })

  it('formats a value >= 1000 with a thousands separator', () => {
    expect(formatCurrency(1234.5)).toBe('$1,234.50')
  })

  it('formats zero', () => {
    expect(formatCurrency(0)).toBe('$0.00')
  })
})

describe('formatNullableCurrency', () => {
  it('formats a present value the same way formatCurrency does', () => {
    expect(formatNullableCurrency(1234.5)).toBe('$1,234.50')
  })

  it("renders '—' for null", () => {
    expect(formatNullableCurrency(null)).toBe('—')
  })

  it("renders '—' for undefined", () => {
    expect(formatNullableCurrency(undefined)).toBe('—')
  })
})

describe('formatSignedSpread', () => {
  it('prefixes a positive difference with a leading +', () => {
    expect(formatSignedSpread(210, 90, '—')).toBe('+120')
  })

  it('leaves a negative difference with its own leading -', () => {
    expect(formatSignedSpread(50, 90, '—')).toBe('-40')
  })

  it('renders 0 as a plain "0", not "+0"', () => {
    expect(formatSignedSpread(50, 50, '—')).toBe('0')
  })

  it('renders the given fallback when a is null', () => {
    expect(formatSignedSpread(null, 90, '—')).toBe('—')
  })

  it('renders the given fallback when b is undefined', () => {
    expect(formatSignedSpread(210, undefined, 'not enough history yet')).toBe(
      'not enough history yet',
    )
  })
})

describe('formatDate', () => {
  it('formats an ISO date-time string as a short human-readable date', () => {
    expect(formatDate('2026-09-18T14:03:00Z')).toBe('Sep 18, 2026')
  })

  it('formats a plain ISO date string the same way', () => {
    expect(formatDate('2026-01-05')).toBe('Jan 5, 2026')
  })
})
